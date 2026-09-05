import os
import re
import json
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import (
    create_engine, String, Text, Integer, Boolean, DateTime,
    ForeignKey, select, or_
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
load_dotenv()

BASE = Path(__file__).resolve().parent
DATA = BASE.parent / "data"
UPLOADS = DATA / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bis_intelligence.db")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@bis-intelligence.local")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@12345")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
NVIDIA_API_URL = os.getenv(
    "NVIDIA_API_URL",
    "https://integrate.api.nvidia.com/v1/chat/completions",
).strip()
NVIDIA_MODEL = os.getenv(
    "NVIDIA_MODEL",
    "nvidia/nemotron-3-super-120b-a12b",
).strip() or "nvidia/nemotron-3-super-120b-a12b"
NVIDIA_TIMEOUT = int(os.getenv("NVIDIA_TIMEOUT", "90"))

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ---------------------------------------------------------
# Database models
# ---------------------------------------------------------
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="USER")
    language: Mapped[str] = mapped_column(String(10), default="en")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    standard_number: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(150), default="General")
    version: Mapped[str] = mapped_column(String(100), default="Demo")
    source_url: Mapped[str] = mapped_column(
        String(1000), default="https://www.bis.gov.in/"
    )
    source_type: Mapped[str] = mapped_column(String(100), default="BIS Official")
    status: Mapped[str] = mapped_column(String(30), default="CURRENT")
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    query: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(60), default="GENERAL_BIS_QUERY")
    confidence: Mapped[str] = mapped_column(String(20), default="LOW")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


Base.metadata.create_all(engine)


# ---------------------------------------------------------
# Dependencies / security
# ---------------------------------------------------------
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def hash_password(password: str, salt: Optional[bytes] = None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, 120_000
    )
    return salt.hex() + ":" + digest.hex()


def verify_password(password: str, stored: str):
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        test = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            bytes.fromhex(salt_hex),
            120_000,
        ).hex()
        return secrets.compare_digest(test, digest_hex)
    except Exception:
        return False


def token_for(user: User):
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    s: Session = Depends(db),
):
    if not creds:
        return None

    try:
        data = jwt.decode(
            creds.credentials,
            JWT_SECRET,
            algorithms=["HS256"],
        )
        return s.get(User, int(data["sub"]))
    except Exception:
        return None


def require_admin(u=Depends(current_user)):
    if not u or u.role != "ADMIN":
        raise HTTPException(403, "Admin access required")
    return u


# ---------------------------------------------------------
# FastAPI
# ---------------------------------------------------------
app = FastAPI(
    title="BIS Intelligence API",
    version="2.0.0",
    description="Evidence-first BIS standards intelligence and compliance prototype",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Multilingual UI messages
# ---------------------------------------------------------
translations = {
    "en": {
        "insufficient": (
            "I could not verify this from the available authoritative "
            "knowledge base. I will not invent a compliance answer."
        ),
        "match": "Potentially applicable standard",
        "why": "Why it matches",
        "roadmap": "Compliance roadmap",
    },
    "hi": {
        "insufficient": (
            "उपलब्ध आधिकारिक ज्ञान आधार से मैं इसे सत्यापित नहीं कर सका। "
            "मैं बिना प्रमाण के अनुपालन उत्तर नहीं बनाऊँगा।"
        ),
        "match": "संभावित रूप से लागू मानक",
        "why": "यह क्यों मेल खाता है",
        "roadmap": "अनुपालन रोडमैप",
    },
    "mr": {
        "insufficient": (
            "उपलब्ध अधिकृत ज्ञानस्रोतांमधून हे सत्यापित करता आले नाही. "
            "पुराव्याशिवाय अनुपालनाचे उत्तर दिले जाणार नाही."
        ),
        "match": "संभाव्यतः लागू मानक",
        "why": "हे का जुळते",
        "roadmap": "अनुपालन रोडमॅप",
    },
}


# ---------------------------------------------------------
# Intent detection
# ---------------------------------------------------------
def infer_intent(q: str):
    ql = q.lower()

    if any(x in ql for x in [
        "standard", "is ", "मानक", "स्टँडर्ड"
    ]):
        return "FIND_STANDARD"

    if any(x in ql for x in [
        "certif", "licen", "प्रमाण", "लायसन्स"
    ]):
        return "CHECK_CERTIFICATION"

    if any(x in ql for x in [
        "test", "testing", "lab", "परीक्षण", "प्रयोगशाळा"
    ]):
        return "TESTING_REQUIREMENTS"

    if any(x in ql for x in [
        "compare", "difference", "तुलना"
    ]):
        return "STANDARD_COMPARISON"

    if any(x in ql for x in [
        "document", "pdf", "दस्तऐवज"
    ]):
        return "DOCUMENT_EXPLANATION"

    return "GENERAL_BIS_QUERY"


# ---------------------------------------------------------
# RAG helpers
# ---------------------------------------------------------
def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_text(text: str, size: int = 1000, overlap: int = 150):
    """Create overlapping chunks so retrieval can return precise evidence."""
    text = normalize_text(text)

    if not text:
        return []

    if overlap >= size:
        overlap = max(0, size // 5)

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end].strip()

        if piece:
            chunks.append(piece)

        if end >= len(text):
            break

        start = max(end - overlap, start + 1)

    return chunks


def retrieve_chunks(s: Session, q: str, k: int = 8):
    """
    Real local RAG retrieval:
    query -> TF-IDF over stored chunks -> cosine similarity -> evidence.
    Only CURRENT documents are searched.
    """
    rows = s.execute(
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.status == "CURRENT")
    ).all()

    if not rows:
        return []

    # Product-specific BIS routing. TF-IDF alone can miss short queries such as
    # "BIS standard applicable on helmet" because the demo corpus is small.
    # For well-known product families, route directly to the relevant official
    # standards before falling back to semantic similarity.
    ql = q.lower()
    priority_standards = []
    if any(k in ql for k in ["helmet", "हेल्मेट", "हेलमेट", "हेल्मेट"]):
        motorcycle = any(k in ql for k in [
            "motorcycle", "motorbike", "motor cycle", "two wheeler",
            "two-wheeler", "bike", "scooter", "दुपहिया", "दोनचाकी",
            "मोटरसायकल", "मोटरसाइकिल"
        ])
        industrial = any(k in ql for k in [
            "industrial", "construction", "factory", "worker", "workers",
            "mine", "mining", "industry", "औद्योगिक", "कामगार", "निर्माण"
        ])
        bicycle = any(k in ql for k in [
            "bicycle", "bike cycle", "cycling", "skateboard",
            "roller skate", "सायकल", "साइकिल"
        ])
        if motorcycle:
            priority_standards = ["IS 4151:2015"]
        elif industrial:
            priority_standards = ["IS 2925:1984"]
        elif bicycle:
            priority_standards = ["IS 18808:2025"]
        else:
            # Ambiguous "helmet" query: show the road-rider standard first,
            # then distinguish industrial and bicycle helmets.
            priority_standards = ["IS 4151:2015", "IS 2925:1984", "IS 18808:2025"]

    texts = [
        f"{doc.title} {doc.standard_number or ''} "
        f"{doc.category} {chunk.section or ''} {chunk.text}"
        for chunk, doc in rows
    ]

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        max_features=12000,
    )

    try:
        matrix = vectorizer.fit_transform(texts + [q])
    except ValueError:
        return []

    scores = cosine_similarity(
        matrix[-1],
        matrix[:-1],
    ).flatten()

    order = scores.argsort()[::-1]

    results = []
    used = set()

    # Deterministic product-to-standard matches outrank generic TF-IDF matches.
    # This is what prevents a query about motorcycle helmets from being routed
    # to an unrelated consumer-product document.
    for standard in priority_standards:
        for idx, (chunk, doc) in enumerate(rows):
            if doc.standard_number == standard and doc.id not in used:
                results.append({
                    "chunk": chunk,
                    "document": doc,
                    "score": 0.99,
                })
                used.add(doc.id)
                break
        if len(results) >= k:
            return results[:k]

    for idx in order:
        score = float(scores[idx])

        if score <= 0:
            continue

        chunk, doc = rows[idx]

        if doc.id in used:
            continue

        results.append({
            "chunk": chunk,
            "document": doc,
            "score": score,
        })

        if len(results) >= k:
            break

    return results


def confidence_from_score(score: float) -> str:
    if score >= 0.35:
        return "HIGH"
    if score >= 0.12:
        return "MEDIUM"
    return "LOW"


def evidence_payload(item):
    chunk = item["chunk"]
    doc = item["document"]
    score = item["score"]

    return {
        "chunk_id": chunk.id,
        "document_id": doc.id,
        "standard": doc.standard_number,
        "title": doc.title,
        "category": doc.category,
        "version": doc.version,
        "status": doc.status,
        "retrieval_match": round(score * 100),
        "confidence": confidence_from_score(score),
        "source": {
            "title": doc.title,
            "type": doc.source_type,
            "url": doc.source_url,
            "verified": doc.verified,
        },
        "evidence": [{
            "section": chunk.section or "Extracted document",
            "page": chunk.page,
            "text": chunk.text[:800],
        }],
    }


# ---------------------------------------------------------
# Seed demo knowledge base
# ---------------------------------------------------------
def seed(s: Session):
    if not s.scalar(select(User).where(User.email == ADMIN_EMAIL)):
        s.add(
            User(
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                role="ADMIN",
            )
        )

    # Original demo records are seeded only when the database is empty.
    if not s.scalar(select(Document)):
        path = DATA / "demo" / "standards.json"
        if path.exists():
            records = json.loads(path.read_text(encoding="utf-8"))
            details = {
                "IS 302 (Part 1):2008": "Safety requirements for household and similar electrical appliances; demo record.",
                "IS 17043:2018": "Demo consumer product standard record.",
                "IS 9845:1998": "Demo food-contact plastics record.",
            }
            for r in records:
                content = details.get(r["standard"], "")
                d = Document(
                    title=r["standard"], standard_number=r["standard"],
                    category=r["category"], version="Demo",
                    source_url="https://www.bis.gov.in/",
                    source_type=r["source_type"], status="CURRENT",
                    content=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    verified=False,
                )
                s.add(d); s.flush()
                for i, piece in enumerate(chunk_text(content)):
                    s.add(Chunk(document_id=d.id, text=piece, page=1, section=f"Demo section {i + 1}"))

    # Authoritative BIS product mappings. These are deliberately explicit so
    # the assistant can answer standard-applicability questions from evidence
    # instead of guessing from a generic language model response.
    authoritative = [
        {
            "standard": "IS 4151:2015",
            "title": "Protective helmets for motorcycle riders – Specification (Fourth Revision)",
            "category": "Protective helmets / two-wheeler riders",
            "version": "2015",
            "url": "https://www.bis.gov.in/is-4151-2015/?lang=en",
            "content": (
                "IS 4151:2015 specifies protective helmets for motorcycle riders and is the Indian Standard "
                "for protective helmets for two-wheeler riders. It covers protective helmets for everyday use "
                "by motorcycle and two-wheeler riders. The Ministry of Road Transport and Highways Helmet for "
                "riders of Two Wheeler Motor Vehicles (Quality Control) Order, 2020 lists IS 4151:2015 and states "
                "that covered goods shall conform to the corresponding Indian Standard and bear the Standard Mark "
                "under a BIS licence; the Order commenced on 1 June 2021. Latest notified versions and amendments apply. "
                "Keywords: helmet, motorcycle helmet, motorbike helmet, scooter helmet, two wheeler helmet, bike helmet, "
                "हेल्मेट, हेलमेट, मोटरसाइकिल हेलमेट, दोपहिया हेलमेट, दुचाकी हेल्मेट.\n"
            ),
        },
        {
            "standard": "IS 2925:1984",
            "title": "Specification for industrial safety helmets (Second Revision)",
            "category": "Industrial safety helmets",
            "version": "1984 (Second Revision)",
            "url": "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/scheme-i-mark-scheme/?lang=en",
            "content": (
                "IS 2925:1984 specifies industrial safety helmets. It applies to safety helmets used for protection "
                "against hazards such as impact from falling objects in industrial and work environments. BIS lists "
                "IS 2925:1984 under Scheme-I compulsory certification products. It is not the motorcycle/two-wheeler "
                "helmet standard; motorcycle riders are covered by IS 4151:2015. Keywords: industrial helmet, safety helmet, "
                "construction helmet, factory helmet, worker helmet, औद्योगिक हेलमेट, कामगार हेल्मेट.\n"
            ),
        },
        {
            "standard": "IS 18808:2025",
            "title": "Protective Helmet for Users of Bicycles, Skateboards and Roller Skates — Specification",
            "category": "Bicycle / skateboard / roller-skate helmets",
            "version": "2025",
            "url": "https://www.services.bis.gov.in/php/BIS_2.0/bisconnect/sfile/sstore2/news_2025-03-03.pdf",
            "content": (
                "IS 18808:2025 specifies protective helmets for users of bicycles, skateboards and roller skates. "
                "It is distinct from IS 4151:2015, which covers protective helmets for motorcycle/two-wheeler riders. "
                "Keywords: bicycle helmet, cycling helmet, skateboard helmet, roller skate helmet, सायकल हेल्मेट, साइकिल हेलमेट.\n"
            ),
        },
    ]

    # Authoritative BIS hallmarking knowledge. These records are intentionally
    # explicit so common hallmarking questions are grounded in official BIS
    # material instead of falling through to generic NVIDIA guidance.
    hallmarking = [
        {
            "standard": "BIS Hallmarking Overview",
            "title": "Hallmarking Overview — Bureau of Indian Standards",
            "category": "Hallmarking / precious-metal articles",
            "version": "Current BIS overview",
            "url": "https://www.bis.gov.in/hallmarking-overview/?lang=en",
            "content": (
                "BIS hallmarking is the accurate determination and official recording of the proportionate "
                "content of precious metal in precious metal articles. In India, gold and silver are presently "
                "under the Hallmarking Scheme. Hallmarking protects consumers against adulteration and supports "
                "legal standards of fineness. A jeweller willing to sell hallmarked gold and silver jewellery or "
                "artefacts applies online for BIS registration. Consumers can have jewellery or samples tested at "
                "BIS-recognized Assaying and Hallmarking Centres. Keywords: hallmark, hallmarking, gold, silver, "
                "jewellery, jeweller, purity, fineness, HUID, हॉलमार्क, हॉलमार्किंग, सोना, चांदी, आभूषण, "
                "हॉलमार्किंग क्या है, हॉलमार्किंग म्हणजे काय, सोन्याची शुद्धता, चांदीची शुद्धता.\n"
            ),
        },
        {
            "standard": "IS 1417:2016",
            "title": "Gold and Gold Alloys, Jewellery/Artefacts — Fineness and Marking — Specification",
            "category": "Gold hallmarking",
            "version": "2016",
            "url": "https://www.bis.gov.in/hallmarking-overview/hallmarking-faqs/hallmarking-faq/?lang=en",
            "content": (
                "BIS lists IS 1417:2016 for Gold and Gold Alloys, Jewellery/Artefacts — Fineness and Marking — "
                "Specification as an Indian Standard on hallmarking. It is relevant to gold jewellery and artefacts "
                "and their fineness and marking. Keywords: gold hallmark, gold jewellery, gold purity, IS 1417, "
                "सोने का हॉलमार्क, सोने की शुद्धता, सोन्याचा हॉलमार्क, IS 1417.\n"
            ),
        },
        {
            "standard": "IS 2112:2025",
            "title": "Silver and Silver Alloys, Jewellery/Artefacts — Fineness and Marking — Specification",
            "category": "Silver hallmarking",
            "version": "2025",
            "url": "https://www.bis.gov.in/hallmarking-overview/hallmarking-faqs/hallmarking-faq/?lang=en",
            "content": (
                "BIS identifies IS 2112:2025 for Silver and Silver Alloys, Jewellery/Artefacts — Fineness and "
                "Marking — Specification. BIS has stated that HUID-based hallmarking under the revised silver "
                "standard is voluntary effective from 1 September 2025. Keywords: silver hallmark, silver jewellery, "
                "silver purity, IS 2112, चांदी हॉलमार्क, चांदीची शुद्धता.\n"
            ),
        },
        {
            "standard": "HUID",
            "title": "Hallmark Unique Identification (HUID) — BIS Hallmarking FAQ",
            "category": "Hallmarking / consumer verification",
            "version": "Current BIS FAQ",
            "url": "https://www.bis.gov.in/hallmarking-overview/hallmarking-faqs/hallmarking-faq/?lang=en",
            "content": (
                "HUID means Hallmark Unique Identification number. BIS states that HUID is a six-digit alphanumeric "
                "number unique for each hallmarked item and traceable. Consumers can use the BIS CARE App's Verify "
                "HUID feature. BIS states that since 1 July 2021, hallmarking on gold jewellery consists of the BIS "
                "logo, purity/fineness and the six-digit alphanumeric HUID number. Keywords: HUID, verify HUID, BIS "
                "CARE, hallmark number, HUID नंबर, HUID क्रमांक.\n"
            ),
        },
        {
            "standard": "BIS (Hallmarking) Regulations, 2018",
            "title": "BIS (Hallmarking) Regulations, 2018",
            "category": "Hallmarking regulation",
            "version": "2018 with amendments",
            "url": "https://www.bis.gov.in/hallmarking-overview/hallmarking-regulation-2018/?lang=en",
            "content": (
                "The BIS (Hallmarking) Regulations, 2018 cover grant of registration for jewellers, recognition "
                "for Assaying and Hallmarking Centres, and grant of licence for refineries. BIS publishes amendments "
                "and related hallmarking orders on its official hallmarking pages. Always check the latest official BIS "
                "amendments and mandatory hallmarking order before making a compliance decision. Keywords: jeweller "
                "registration, Assaying and Hallmarking Centre, refinery, hallmarking regulations, नियम, नोंदणी.\n"
            ),
        },
        {
            "standard": "Mandatory Hallmarking Order",
            "title": "Mandatory Hallmarking Order — BIS",
            "category": "Mandatory hallmarking / Quality Control Order",
            "version": "Current BIS order page",
            "url": "https://www.bis.gov.in/hallmarking-overview/mandatory-hallmarking-order/?lang=en",
            "content": (
                "BIS maintains the current Mandatory Hallmarking Order page and publishes amendments and Quality "
                "Control Orders there. The page currently lists amendments through 3 August 2026. Because mandatory "
                "coverage can change through notifications and amendments, questions about whether a particular article, "
                "purity grade, district or date is covered should be checked against the latest official BIS order and "
                "amendments. Keywords: mandatory hallmarking, mandatory hallmark, QCO, order, compulsory, अनिवार्य "
                "हॉलमार्किंग, अनिवार्य हॉलमार्क, अनिवार्य.\n"
            ),
        },
    ]
    authoritative.extend(hallmarking)

    for r in authoritative:
        existing = s.scalar(select(Document).where(Document.standard_number == r["standard"]))
        if existing:
            # Upgrade an old placeholder record to authoritative metadata.
            existing.title = r["title"]
            existing.category = r["category"]
            existing.version = r["version"]
            existing.source_url = r["url"]
            existing.source_type = "BIS Official"
            existing.status = "CURRENT"
            existing.content = r["content"]
            existing.content_hash = hashlib.sha256(r["content"].encode()).hexdigest()
            existing.verified = True
            s.query(Chunk).filter(Chunk.document_id == existing.id).delete()
            doc = existing
        else:
            doc = Document(
                title=r["title"], standard_number=r["standard"],
                category=r["category"], version=r["version"],
                source_url=r["url"], source_type="BIS Official",
                status="CURRENT", content=r["content"],
                content_hash=hashlib.sha256(r["content"].encode()).hexdigest(),
                verified=True,
            )
            s.add(doc); s.flush()
        for i, piece in enumerate(chunk_text(r["content"], size=900, overlap=120)):
            s.add(Chunk(document_id=doc.id, text=piece, page=1, section=f"Applicability {i + 1}"))

    # Load the comprehensive BIS domain knowledge registry.
    # These are official-source summaries/navigation records. The optional
    # sync script refreshes public BIS web/PDF material into the same database.
    comprehensive_path = DATA / "bis_official" / "comprehensive_knowledge.json"
    if comprehensive_path.exists():
        records = json.loads(comprehensive_path.read_text(encoding="utf-8"))
        for r in records:
            content = r["content"]
            existing = s.scalar(select(Document).where(Document.standard_number == r["standard"]))
            if existing:
                existing.title = r["title"]
                existing.category = r["category"]
                existing.version = r["version"]
                existing.source_url = r["url"]
                existing.source_type = "BIS Official"
                existing.status = "CURRENT"
                existing.content = content
                existing.content_hash = hashlib.sha256(content.encode()).hexdigest()
                existing.verified = True
                s.query(Chunk).filter(Chunk.document_id == existing.id).delete()
                doc = existing
            else:
                doc = Document(
                    title=r["title"], standard_number=r["standard"],
                    category=r["category"], version=r["version"],
                    source_url=r["url"], source_type="BIS Official",
                    status="CURRENT", content=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    verified=True,
                )
                s.add(doc); s.flush()
            for i, piece in enumerate(chunk_text(content, size=1000, overlap=140)):
                s.add(Chunk(document_id=doc.id, text=piece, page=1, section=f"BIS domain knowledge {i + 1}"))

    s.commit()


with SessionLocal() as s:
    seed(s)


# ---------------------------------------------------------
# Request models
# ---------------------------------------------------------
class AuthIn(BaseModel):
    email: EmailStr
    password: str
    language: str = "en"


class AnalyzeIn(BaseModel):
    query: str
    language: str = "en"


class VoiceSearchIn(BaseModel):
    transcript: str
    language: str = "en"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    language: str = "en"


class VerifyDocumentIn(BaseModel):
    verified: bool = True


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------
@app.get("/")
def root():
    return {
        "service": "BIS Intelligence API",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "bis-intelligence-api",
        "database": "connected",
        "rag": "chunk-tfidf",
        "llm_provider": "NVIDIA NIM",
        "llm_model": NVIDIA_MODEL,
        "llm_configured": bool(NVIDIA_API_KEY),
    }


# ---------------------------------------------------------
# Authentication
# ---------------------------------------------------------
@app.post("/api/auth/register")
def register(x: RegisterIn, s: Session = Depends(db)):
    if len(x.password) < 8:
        raise HTTPException(
            422,
            "Password must be at least 8 characters",
        )

    if s.scalar(select(User).where(User.email == x.email)):
        raise HTTPException(
            409,
            "Email already registered",
        )

    language = x.language if x.language in translations else "en"

    u = User(
        email=x.email,
        password_hash=hash_password(x.password),
        language=language,
    )

    s.add(u)
    s.commit()
    s.refresh(u)

    return {
        "token": token_for(u),
        "user": {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "language": u.language,
        },
    }


@app.post("/api/auth/login")
def login(x: AuthIn, s: Session = Depends(db)):
    u = s.scalar(
        select(User).where(User.email == x.email)
    )

    if not u or not verify_password(
        x.password,
        u.password_hash,
    ):
        raise HTTPException(
            401,
            "Invalid email or password",
        )

    return {
        "token": token_for(u),
        "user": {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "language": u.language,
        },
    }


@app.get("/api/auth/me")
def me(u=Depends(current_user)):
    if not u:
        raise HTTPException(
            401,
            "Authentication required",
        )

    return {
        "id": u.id,
        "email": u.email,
        "role": u.role,
        "language": u.language,
    }


# ---------------------------------------------------------
# Voice search API
# ---------------------------------------------------------
@app.post("/api/voice/search")
def voice_search(
    x: VoiceSearchIn,
    s: Session = Depends(db),
    u=Depends(current_user),
):
    """
    Voice-to-search bridge.

    The browser performs speech-to-text using the selected Indian locale
    (en-IN, hi-IN or mr-IN). This endpoint receives the resulting transcript
    and runs it through the same grounded BIS RAG pipeline as typed search.
    No speech text is fabricated or silently translated.
    """
    transcript = x.transcript.strip()

    if not transcript:
        raise HTTPException(422, "Voice transcript is empty.")

    language = x.language if x.language in translations else "en"

    return analyze(
        AnalyzeIn(query=transcript, language=language),
        s,
        u,
    )


# ---------------------------------------------------------
# ---------------------------------------------------------
# NVIDIA NIM answer generation
# ---------------------------------------------------------

def _nvidia_unavailable_message(language: str) -> str:
    messages = {
        "en": "NVIDIA AI is temporarily unavailable. No local or hardcoded answer was substituted. Please try Analyze again shortly.",
        "hi": "NVIDIA AI इस समय अस्थायी रूप से उपलब्ध नहीं है। किसी स्थानीय या हार्डकोड उत्तर को विकल्प के रूप में उपयोग नहीं किया गया है। कृपया थोड़ी देर बाद फिर से Analyze करें।",
        "mr": "NVIDIA AI सध्या तात्पुरते उपलब्ध नाही. स्थानिक किंवा हार्डकोड केलेले उत्तर पर्याय म्हणून वापरलेले नाही. कृपया थोड्या वेळाने पुन्हा Analyze करा.",
    }
    return messages.get(language, messages["en"])


def nvidia_status():
    return {
        "configured": bool(NVIDIA_API_KEY),
        "provider": "NVIDIA NIM",
        "model": NVIDIA_MODEL,
        "endpoint": NVIDIA_API_URL,
        "timeout_seconds": NVIDIA_TIMEOUT,
    }


@app.get("/api/nvidia/status")
def nvidia_status_endpoint():
    return nvidia_status()


def generate_nvidia_answer(query: str, language: str, evidence: list[dict]):
    """Generate the final answer through NVIDIA NIM, grounded in retrieved BIS evidence."""
    if not NVIDIA_API_KEY:
        raise HTTPException(
            503,
            "NVIDIA API key is not configured. Add NVIDIA_API_KEY to backend/.env and restart the backend.",
        )

    language_name = {
        "en": "English",
        "hi": "Hindi",
        "mr": "Marathi",
    }.get(language, "English")

    evidence_text = []
    for i, item in enumerate(evidence[:8], 1):
        ev = (item.get("evidence") or [{}])[0]
        source = item.get("source") or {}
        evidence_text.append(
            f"BIS EVIDENCE {i}\n"
            f"Standard: {item.get('standard') or 'Not specified'}\n"
            f"Title: {item.get('title') or 'Not specified'}\n"
            f"Category: {item.get('category') or 'Not specified'}\n"
            f"Version: {item.get('version') or 'Not specified'}\n"
            f"Status: {item.get('status') or 'Not specified'}\n"
            f"Source title: {source.get('title') or item.get('title') or 'Not specified'}\n"
            f"Source URL: {source.get('url') or 'Not specified'}\n"
            f"Verified: {source.get('verified', False)}\n"
            f"Evidence text: {ev.get('text') or 'No extracted text'}\n"
        )

    context = "\n\n---\n\n".join(evidence_text) if evidence_text else "No matching BIS evidence was retrieved."

    system_prompt = f"""
You are BIS Intelligence, an AI assistant for the Bureau of Indian Standards (BIS).
Answer the user's question in {language_name}.

ACCURACY RULES:
1. Use the supplied BIS evidence as the primary source for BIS-specific claims.
2. Never invent an IS number, QCO, licence requirement, test, fee, date, certification rule,
   standard version, government rule, or source.
3. If the supplied evidence does not establish a BIS-specific fact, explicitly say it could not
   be verified from the available BIS evidence instead of guessing.
4. Clearly distinguish a BIS Standard, Quality Control Order (QCO), BIS certification/licence,
   testing requirement, and general guidance.
5. If multiple evidence items conflict, state the conflict and do not silently choose one.
6. For compliance questions, explain the practical next steps and identify what must be verified
   from the latest official BIS/Government source.
7. You are the final answer engine. Do not substitute a local hardcoded answer.
8. Keep the answer concise but complete. Use bullets where helpful.
""".strip()

    user_prompt = f"""
USER QUESTION:
{query}

RETRIEVED BIS EVIDENCE:
{context}

Provide the best-supported answer. For BIS-specific facts, cite the relevant evidence by naming
its IS number/title when available. Do not claim that you performed a live web search.
""".strip()

    payload = {
        "model": NVIDIA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.7,
        "max_tokens": 4096,
        "stream": False,
    }

    request = Request(
        NVIDIA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    import time
    delays = [1.5, 3.0, 6.0]
    last_error = "NVIDIA API request failed."
    last_status = None

    for attempt in range(3):
        try:
            with urlopen(request, timeout=NVIDIA_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw)

            choices = data.get("choices") or []
            answer = ""
            if choices:
                answer = ((choices[0].get("message") or {}).get("content") or "").strip()

            if not answer:
                raise ValueError("NVIDIA returned an empty response.")

            return answer

        except HTTPError as exc:
            last_status = exc.code
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = str(exc)
            last_error = body[:700]
            print(f"NVIDIA API error {exc.code}, attempt={attempt + 1}/3: {last_error}")
            if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(delays[attempt])
                continue
            break
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = str(exc)
            print(f"NVIDIA connection/response error, attempt={attempt + 1}/3: {last_error}")
            if attempt < 2:
                time.sleep(delays[attempt])
                continue
            break

    print(f"All NVIDIA attempts failed; status={last_status}, error={last_error}")
    raise HTTPException(503, _nvidia_unavailable_message(language))


# ---------------------------------------------------------
# BIS knowledge catalog/status
# ---------------------------------------------------------
@app.get("/api/bis/catalog")
def bis_catalog():
    registry = DATA / "bis_official" / "source_registry.json"
    if not registry.exists():
        return {"sources": [], "knowledge_domains": []}
    return json.loads(registry.read_text(encoding="utf-8"))


@app.get("/api/bis/knowledge-status")
def bis_knowledge_status(s: Session = Depends(db)):
    docs = s.execute(select(Document).where(Document.source_type == "BIS Official")).scalars().all()
    chunks = s.execute(select(Chunk).join(Document, Chunk.document_id == Document.id).where(Document.source_type == "BIS Official")).scalars().all()
    return {
        "official_documents_indexed": len(docs),
        "official_chunks_indexed": len(chunks),
        "live_sync_script": "scripts/sync_bis.py",
        "know_your_standard": "https://www.bis.gov.in/know-your-standard/?lang=en",
        "note": "The packaged knowledge is a broad official BIS domain base. Run the sync script periodically to refresh public BIS web/PDF material; no static package can guarantee every current Indian Standard forever."
    }


# ---------------------------------------------------------
# Main RAG + compliance analysis
# ---------------------------------------------------------
@app.post("/api/compliance/analyze")
def analyze(
    x: AnalyzeIn,
    s: Session = Depends(db),
    u=Depends(current_user),
):
    q = x.query.strip()
    lang = x.language if x.language in translations else "en"

    if not q:
        return {
            "status": "insufficient_evidence",
            "message": translations[lang]["insufficient"],
            "sources": [],
        }

    hits = retrieve_chunks(s, q, k=8)
    intent = infer_intent(q)
    top_score = hits[0]["score"] if hits else 0
    confidence = confidence_from_score(top_score)

    s.add(
        QueryLog(
            user_id=u.id if u else None,
            query=q,
            intent=intent,
            confidence=confidence,
        )
    )
    s.commit()

    results = [evidence_payload(item) for item in hits]
    nvidia_answer = generate_nvidia_answer(q, lang, results)

    if not hits or confidence == "LOW":
        return {
            "status": "general_answer",
            "message": translations[lang]["insufficient"],
            "intent": intent,
            "confidence": confidence,
            "sources": [],
            "grounding_sources": [item.get("source", {}) for item in results],
            "nvidia_answer": nvidia_answer,
            "answer": {
                "headline": "NVIDIA answer",
                "nvidia": nvidia_answer,
                "roadmap": [],
                "disclaimer": "NVIDIA generated this answer from the retrieved BIS evidence. Verify the latest official BIS/Government source before making a compliance decision.",
            },
        }

    top = results[0]
    roadmap = [
        "Identify the potentially applicable standard",
        "Verify the latest standard version and amendments",
        "Verify whether BIS certification/licensing applies",
        "Check required tests and inspection steps",
        "Prepare technical and application documents",
        "Select a laboratory with required capability",
        "Submit through the applicable official BIS process",
        "Maintain evidence and monitor amendments",
    ]

    return {
        "status": "grounded",
        "query": q,
        "intent": intent,
        "confidence": confidence,
        "results": results,
        "nvidia_answer": nvidia_answer,
        "grounding_sources": [item.get("source", {}) for item in results],
        "nvidia_model": NVIDIA_MODEL,
        "answer": {
            "headline": translations[lang]["match"],
            "why": [
                f"Retrieved evidence from {top['standard'] or top['title']}",
                "The result is based on indexed document chunks",
                "Page/section evidence is attached to each result",
                "Only CURRENT documents participate in retrieval",
            ],
            "nvidia": nvidia_answer,
            "roadmap": roadmap,
            "disclaimer": (
                "Prototype information. Verify current applicability "
                "with official BIS sources before compliance decisions."
            ),
        },
    }


# ---------------------------------------------------------
# Checklist
# ---------------------------------------------------------
@app.post("/api/compliance/checklist")
def compliance_checklist(
    x: AnalyzeIn,
    s: Session = Depends(db),
    u=Depends(current_user),
):
    hits = retrieve_chunks(s, x.query, 5)

    if not hits:
        return {
            "status": "insufficient_evidence",
            "items": [],
            "message": translations.get(
                x.language,
                translations["en"],
            )["insufficient"],
        }

    top = hits[0]["document"]

    base = [
        "Identify the applicable standard",
        "Confirm the latest version and amendments",
        "Verify whether BIS certification/licensing applies",
        "Confirm required tests and inspection steps",
        "Prepare technical and application documents",
        "Select a laboratory with the required capability",
        "Submit through the applicable official BIS process",
        "Maintain evidence and monitor amendments",
    ]

    return {
        "status": "grounded",
        "standard": top.standard_number,
        "items": [
            {
                "id": i + 1,
                "label": label,
                "required": True,
                "evidence_source": top.title,
            }
            for i, label in enumerate(base)
        ],
        "disclaimer": (
            "Checklist is an AI-assisted planning aid, "
            "not a certification decision."
        ),
    }


# ---------------------------------------------------------
# Standards
# ---------------------------------------------------------
@app.get("/api/standards")
def standards(
    q: Optional[str] = None,
    s: Session = Depends(db),
):
    if q:
        hits = retrieve_chunks(s, q, 20)

        # Deduplicate documents returned through multiple chunks.
        seen = set()
        docs = []

        for item in hits:
            d = item["document"]
            if d.id not in seen:
                seen.add(d.id)
                docs.append(d)
    else:
        docs = list(
            s.scalars(
                select(Document)
                .where(Document.status != "OBSOLETE")
                .order_by(Document.id.desc())
            ).all()
        )

    return [
        {
            "id": d.id,
            "standard": d.standard_number,
            "title": d.title,
            "category": d.category,
            "version": d.version,
            "status": d.status,
            "verified": d.verified,
            "source_url": d.source_url,
        }
        for d in docs
    ]


# ---------------------------------------------------------
# Evidence endpoint
# ---------------------------------------------------------
@app.get("/api/evidence/{document_id}")
def document_evidence(
    document_id: int,
    s: Session = Depends(db),
):
    d = s.get(Document, document_id)

    if not d:
        raise HTTPException(404, "Document not found")

    chunks = list(
        s.scalars(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.page, Chunk.id)
        ).all()
    )

    return {
        "document": {
            "id": d.id,
            "title": d.title,
            "standard_number": d.standard_number,
            "category": d.category,
            "version": d.version,
            "status": d.status,
            "verified": d.verified,
            "source": {
                "type": d.source_type,
                "url": d.source_url,
            },
        },
        "chunks": [
            {
                "id": c.id,
                "page": c.page,
                "section": c.section,
                "text": c.text,
            }
            for c in chunks
        ],
    }


# ---------------------------------------------------------
# Admin
# ---------------------------------------------------------
@app.get("/api/admin/overview")
def admin_overview(
    s: Session = Depends(db),
    u=Depends(require_admin),
):
    docs = list(s.scalars(select(Document)).all())
    logs = list(s.scalars(select(QueryLog)).all())
    users = list(s.scalars(select(User)).all())

    low = sum(
        1 for x in logs
        if x.confidence == "LOW"
    )

    return {
        "documents": len(docs),
        "current_documents": sum(
            d.status == "CURRENT"
            for d in docs
        ),
        "verified_documents": sum(
            d.verified
            for d in docs
        ),
        "obsolete_documents": sum(
            d.status == "OBSOLETE"
            for d in docs
        ),
        "queries": len(logs),
        "low_confidence_queries": low,
        "users": len(users),
    }


@app.get("/api/admin/queries")
def admin_queries(
    s: Session = Depends(db),
    u=Depends(require_admin),
):
    logs = list(
        s.scalars(
            select(QueryLog)
            .order_by(QueryLog.id.desc())
            .limit(50)
        ).all()
    )

    return [
        {
            "query": x.query,
            "intent": x.intent,
            "confidence": x.confidence,
            "created_at": x.created_at.isoformat(),
        }
        for x in logs
    ]


@app.get("/api/admin/documents")
def admin_docs(
    s: Session = Depends(db),
    u=Depends(require_admin),
):
    docs = list(
        s.scalars(
            select(Document)
            .order_by(Document.id.desc())
        ).all()
    )

    return [
        {
            "id": d.id,
            "title": d.title,
            "standard_number": d.standard_number,
            "version": d.version,
            "status": d.status,
            "verified": d.verified,
            "source_type": d.source_type,
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]


@app.post("/api/admin/documents/{document_id}/verify")
def verify_document(
    document_id: int,
    x: VerifyDocumentIn,
    s: Session = Depends(db),
    u=Depends(require_admin),
):
    d = s.get(Document, document_id)

    if not d:
        raise HTTPException(404, "Document not found")

    d.verified = x.verified
    s.commit()

    return {
        "id": d.id,
        "verified": d.verified,
        "status": d.status,
    }


# ---------------------------------------------------------
# PDF ingestion
# ---------------------------------------------------------
@app.post("/api/admin/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    s: Session = Depends(db),
    u=Depends(require_admin),
):
    filename = file.filename or ""

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            422,
            "Only PDF uploads are supported",
        )

    raw = await file.read()

    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(
            413,
            "Maximum file size is 10 MB",
        )

    digest = hashlib.sha256(raw).hexdigest()
    path = UPLOADS / f"{digest}.pdf"

    # Avoid storing the same physical file twice.
    if not path.exists():
        path.write_bytes(raw)

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise HTTPException(
            422,
            f"Could not read PDF: {exc}",
        )

    pages = []

    for i, page in enumerate(reader.pages, 1):
        txt = normalize_text(
            page.extract_text() or ""
        )

        if txt:
            pages.append((i, txt))

    content = "\n\n".join(
        text for _, text in pages
    )

    if not content:
        raise HTTPException(
            422,
            "No extractable text found in PDF. "
            "Scanned/image-only PDFs need OCR before ingestion.",
        )

    # Try to detect an IS standard number.
    match = re.search(
        r"\bIS\s*[0-9]{2,6}"
        r"(?:\s*\([^)]*\))?"
        r"(?:\s*:\s*[0-9]{4})?",
        content,
        re.I,
    )

    standard_number = (
        match.group(0).strip()
        if match
        else None
    )

    # If the same hash is already indexed, return it.
    existing = s.scalar(
        select(Document).where(
            Document.content_hash == digest
        )
    )

    if existing:
        return {
            "id": existing.id,
            "title": existing.title,
            "pages": len(pages),
            "chunks": s.scalar(
                select(Chunk)
                .where(Chunk.document_id == existing.id)
                .count()
            ) if False else None,
            "standard_number": existing.standard_number,
            "verified": existing.verified,
            "duplicate": True,
        }

    # Versioning:
    # When a new document for the same standard arrives,
    # previous CURRENT versions become OBSOLETE.
    if standard_number:
        previous = list(
            s.scalars(
                select(Document).where(
                    Document.standard_number == standard_number,
                    Document.status == "CURRENT",
                )
            ).all()
        )

        for old in previous:
            old.status = "OBSOLETE"

        version = f"Uploaded-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    else:
        version = "Uploaded"

    d = Document(
        title=filename,
        standard_number=standard_number,
        category="Uploaded document",
        version=version,
        source_url="Local upload",
        source_type="User uploaded",
        status="CURRENT",
        content=content,
        content_hash=digest,
        verified=False,
    )

    s.add(d)
    s.flush()

    total_chunks = 0

    # Preserve page-level evidence while chunking.
    for page_number, page_text in pages:
        pieces = chunk_text(
            page_text,
            size=1000,
            overlap=150,
        )

        for i, piece in enumerate(pieces):
            s.add(
                Chunk(
                    document_id=d.id,
                    text=piece,
                    page=page_number,
                    section=f"PDF page {page_number}, chunk {i + 1}",
                )
            )
            total_chunks += 1

    s.commit()

    return {
        "id": d.id,
        "title": d.title,
        "pages": len(pages),
        "chunks": total_chunks,
        "standard_number": d.standard_number,
        "version": d.version,
        "verified": d.verified,
        "status": d.status,
        "message": (
            "PDF indexed successfully. "
            "The document remains unverified until an admin verifies it."
        ),
    }
