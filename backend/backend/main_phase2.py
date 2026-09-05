import os
import re
import json
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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

    for idx in order:
        score = float(scores[idx])

        if score <= 0:
            continue

        chunk, doc = rows[idx]

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

    if not s.scalar(select(Document)):
        path = DATA / "demo" / "standards.json"

        if path.exists():
            records = json.loads(path.read_text(encoding="utf-8"))

            details = {
                "IS 302 (Part 1):2008": (
                    "Safety requirements for household and similar "
                    "electrical appliances; use this demo record to "
                    "illustrate grounded retrieval for electrical products."
                ),
                "IS 17043:2018": (
                    "Demo consumer product standard record used to "
                    "demonstrate metadata, versioning and evidence cards."
                ),
                "IS 9845:1998": (
                    "Demo food-contact plastics record used to demonstrate "
                    "product/material retrieval and compliance workflows."
                ),
            }

            for r in records:
                content = details.get(r["standard"], "")

                d = Document(
                    title=r["standard"],
                    standard_number=r["standard"],
                    category=r["category"],
                    version="Demo",
                    source_url="https://www.bis.gov.in/",
                    source_type=r["source_type"],
                    status="CURRENT",
                    content=content,
                    content_hash=hashlib.sha256(
                        content.encode()
                    ).hexdigest(),
                    verified=False,
                )

                s.add(d)
                s.flush()

                for i, piece in enumerate(chunk_text(content)):
                    s.add(
                        Chunk(
                            document_id=d.id,
                            text=piece,
                            page=1,
                            section=f"Demo section {i + 1}",
                        )
                    )

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

    if not hits or confidence == "LOW":
        return {
            "status": "insufficient_evidence",
            "message": translations[lang]["insufficient"],
            "intent": intent,
            "confidence": confidence,
            "sources": [],
        }

    results = [
        evidence_payload(item)
        for item in hits
    ]

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
        "answer": {
            "headline": translations[lang]["match"],
            "why": [
                f"Retrieved evidence from {top['standard'] or top['title']}",
                "The result is based on indexed document chunks",
                "Page/section evidence is attached to each result",
                "Only CURRENT documents participate in retrieval",
            ],
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
