import os, re, json, hashlib, secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, String, Text, Integer, Boolean, DateTime, ForeignKey, select, or_
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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

class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default='USER')
    language: Mapped[str] = mapped_column(String(10), default='en')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class Document(Base):
    __tablename__='documents'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    standard_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(150), default='General')
    version: Mapped[str] = mapped_column(String(100), default='Demo')
    source_url: Mapped[str] = mapped_column(String(1000), default='https://www.bis.gov.in/')
    source_type: Mapped[str] = mapped_column(String(100), default='BIS Official')
    status: Mapped[str] = mapped_column(String(30), default='CURRENT')
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class Chunk(Base):
    __tablename__='chunks'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'), index=True)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

class QueryLog(Base):
    __tablename__='query_logs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    query: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(60), default='GENERAL_BIS_QUERY')
    confidence: Mapped[str] = mapped_column(String(20), default='LOW')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

Base.metadata.create_all(engine)


def db():
    s=SessionLocal()
    try: yield s
    finally: s.close()

def hash_password(password: str, salt: Optional[bytes]=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 120_000)
    return salt.hex()+':'+digest.hex()

def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split(':',1)
        test = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt_hex), 120_000).hex()
        return secrets.compare_digest(test, digest_hex)
    except Exception: return False

def token_for(user: User):
    payload={'sub':str(user.id),'role':user.role,'exp':datetime.now(timezone.utc)+timedelta(hours=12)}
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

bearer=HTTPBearer(auto_error=False)
def current_user(creds: HTTPAuthorizationCredentials=Depends(bearer), s: Session=Depends(db)):
    if not creds: return None
    try:
        data=jwt.decode(creds.credentials, JWT_SECRET, algorithms=['HS256'])
        u=s.get(User,int(data['sub']))
        return u
    except Exception: return None

def require_admin(u=Depends(current_user)):
    if not u or u.role!='ADMIN': raise HTTPException(403,'Admin access required')
    return u

app=FastAPI(title='BIS Intelligence API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000','http://127.0.0.1:3000'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

translations={
'en': {'insufficient':'I could not verify this from the available authoritative knowledge base. I will not invent a compliance answer.','match':'Potentially applicable standard','why':'Why it matches','roadmap':'Compliance roadmap'},
'hi': {'insufficient':'उपलब्ध आधिकारिक ज्ञान आधार से मैं इसे सत्यापित नहीं कर सका। मैं बिना प्रमाण के अनुपालन उत्तर नहीं बनाऊँगा।','match':'संभावित रूप से लागू मानक','why':'यह क्यों मेल खाता है','roadmap':'अनुपालन रोडमैप'},
'mr': {'insufficient':'उपलब्ध अधिकृत ज्ञानस्रोतांमधून हे सत्यापित करता आले नाही. पुराव्याशिवाय अनुपालनाचे उत्तर दिले जाणार नाही.','match':'संभाव्यतः लागू मानक','why':'हे का जुळते','roadmap':'अनुपालन रोडमॅप'}
}

def infer_intent(q):
    ql=q.lower()
    if any(x in ql for x in ['standard','is ','मानक','स्टँडर्ड']): return 'FIND_STANDARD'
    if any(x in ql for x in ['certif','licen','प्रमाण','लायसन्स']): return 'CHECK_CERTIFICATION'
    if any(x in ql for x in ['test','testing','lab','परीक्षण','प्रयोगशाळा']): return 'TESTING_REQUIREMENTS'
    if any(x in ql for x in ['compare','difference','तुलना']): return 'STANDARD_COMPARISON'
    if any(x in ql for x in ['document','pdf','दस्तऐवज']): return 'DOCUMENT_EXPLANATION'
    return 'GENERAL_BIS_QUERY'

def retrieve(s: Session, q: str, k=5):
    docs=list(s.scalars(select(Document).where(Document.status!='OBSOLETE')).all())
    if not docs: return []
    texts=[(d.title+' '+(d.standard_number or '')+' '+d.category+' '+d.content) for d in docs]
    vec=TfidfVectorizer(stop_words='english', ngram_range=(1,2), max_features=8000)
    matrix=vec.fit_transform(texts+[q])
    scores=cosine_similarity(matrix[-1],matrix[:-1]).flatten()
    order=scores.argsort()[::-1][:k]
    return [(docs[i],float(scores[i])) for i in order if scores[i]>0]

def seed(s: Session):
    if not s.scalar(select(User).where(User.email==ADMIN_EMAIL)):
        s.add(User(email=ADMIN_EMAIL,password_hash=hash_password(ADMIN_PASSWORD),role='ADMIN'))
    if not s.scalar(select(Document)):
        path=DATA/'demo'/'standards.json'
        records=json.loads(path.read_text(encoding='utf-8'))
        details={
          'IS 302 (Part 1):2008':'Safety requirements for household and similar electrical appliances; use this demo record to illustrate grounded retrieval for electrical products.',
          'IS 17043:2018':'Demo consumer product standard record used to demonstrate metadata, versioning and evidence cards.',
          'IS 9845:1998':'Demo food-contact plastics record used to demonstrate product/material retrieval and compliance workflows.'}
        for r in records:
            d=Document(title=r['standard'],standard_number=r['standard'],category=r['category'],version='Demo',source_url='https://www.bis.gov.in/',source_type=r['source_type'],status='CURRENT',content=details.get(r['standard'],''),content_hash=hashlib.sha256(details.get(r['standard'],'').encode()).hexdigest(),verified=False)
            s.add(d); s.flush(); s.add(Chunk(document_id=d.id,text=d.content,page=1,section='Demo record'))
    s.commit()
with SessionLocal() as s: seed(s)

class AuthIn(BaseModel): email: EmailStr; password: str; language: str='en'
class AnalyzeIn(BaseModel): query: str; language: str='en'
class RegisterIn(BaseModel): email: EmailStr; password: str; language: str='en'

@app.get('/health')
def health(): return {'status':'ok','service':'bis-intelligence-api','database':'connected'}

@app.post('/api/auth/register')
def register(x:RegisterIn,s:Session=Depends(db)):
    if len(x.password)<8: raise HTTPException(422,'Password must be at least 8 characters')
    if s.scalar(select(User).where(User.email==x.email)): raise HTTPException(409,'Email already registered')
    u=User(email=x.email,password_hash=hash_password(x.password),language=x.language if x.language in translations else 'en'); s.add(u); s.commit(); s.refresh(u)
    return {'token':token_for(u),'user':{'id':u.id,'email':u.email,'role':u.role,'language':u.language}}

@app.post('/api/auth/login')
def login(x:AuthIn,s:Session=Depends(db)):
    u=s.scalar(select(User).where(User.email==x.email))
    if not u or not verify_password(x.password,u.password_hash): raise HTTPException(401,'Invalid email or password')
    return {'token':token_for(u),'user':{'id':u.id,'email':u.email,'role':u.role,'language':u.language}}

@app.get('/api/auth/me')
def me(u=Depends(current_user)):
    if not u: raise HTTPException(401,'Authentication required')
    return {'id':u.id,'email':u.email,'role':u.role,'language':u.language}

@app.post('/api/compliance/analyze')
def analyze(x:AnalyzeIn,s:Session=Depends(db),u=Depends(current_user)):
    q=x.query.strip(); lang=x.language if x.language in translations else 'en'
    if not q: return {'status':'insufficient_evidence','message':translations[lang]['insufficient'],'sources':[]}
    hits=retrieve(s,q)
    intent=infer_intent(q)
    confidence='HIGH' if hits and hits[0][1]>=0.35 else 'MEDIUM' if hits and hits[0][1]>=0.12 else 'LOW'
    s.add(QueryLog(user_id=u.id if u else None,query=q,intent=intent,confidence=confidence)); s.commit()
    if not hits or confidence=='LOW': return {'status':'insufficient_evidence','message':translations[lang]['insufficient'],'intent':intent,'confidence':confidence,'sources':[]}
    results=[]
    for d,score in hits:
        results.append({'document_id':d.id,'standard':d.standard_number,'title':d.title,'category':d.category,'retrieval_match':round(score*100),'confidence':confidence,'version':d.version,'status':d.status,'source':{'title':d.title,'type':d.source_type,'url':d.source_url,'verified':d.verified},'evidence':[{'section':'Demo record','page':1,'text':d.content[:350]}]})
    top=results[0]
    roadmap=['Identify applicable standard','Verify certification applicability','Check testing requirements','Prepare required documents','Find an appropriate laboratory','Complete and review checklist']
    return {'status':'grounded_demo','query':q,'intent':intent,'confidence':confidence,'results':results,'answer':{'headline':translations[lang]['match'],'why':[f"Query has strong lexical overlap with {top['standard']}",'Product/category context matched indexed knowledge','Source metadata is attached to the result'],'roadmap':roadmap,'disclaimer':'Prototype information. Verify current applicability with official BIS sources before compliance decisions.'}}

@app.post('/api/compliance/checklist')
def compliance_checklist(x:AnalyzeIn,s:Session=Depends(db),u=Depends(current_user)):
    hits=retrieve(s,x.query,5)
    if not hits:
        return {'status':'insufficient_evidence','items':[],'message':translations.get(x.language,translations['en'])['insufficient']}
    top=hits[0][0]
    base=['Identify the applicable standard','Confirm the latest version and amendments','Verify whether BIS certification/licensing applies','Confirm required tests and inspection steps','Prepare technical and application documents','Select a laboratory with the required capability','Submit through the applicable official BIS process','Maintain evidence and monitor amendments']
    return {'status':'grounded_demo','standard':top.standard_number,'items':[{'id':i+1,'label':label,'required':True,'evidence_source':top.title} for i,label in enumerate(base)],'disclaimer':'Checklist is an AI-assisted planning aid, not a certification decision.'}

@app.get('/api/standards')
def standards(q:Optional[str]=None,s:Session=Depends(db)):
    if q: hits=retrieve(s,q,20); docs=[d for d,_ in hits]
    else: docs=list(s.scalars(select(Document).order_by(Document.id.desc())).all())
    return [{'id':d.id,'standard':d.standard_number,'title':d.title,'category':d.category,'version':d.version,'status':d.status,'verified':d.verified,'source_url':d.source_url} for d in docs]

@app.get('/api/admin/overview')
def admin_overview(s:Session=Depends(db),u=Depends(require_admin)):
    docs=list(s.scalars(select(Document)).all()); logs=list(s.scalars(select(QueryLog)).all())
    low=sum(1 for x in logs if x.confidence=='LOW')
    return {'documents':len(docs),'current_documents':sum(d.status=='CURRENT' for d in docs),'queries':len(logs),'low_confidence_queries':low,'users':len(list(s.scalars(select(User)).all()))}

@app.get('/api/admin/queries')
def admin_queries(s:Session=Depends(db),u=Depends(require_admin)):
    logs=list(s.scalars(select(QueryLog).order_by(QueryLog.id.desc()).limit(50)).all())
    return [{'query':x.query,'intent':x.intent,'confidence':x.confidence,'created_at':x.created_at.isoformat()} for x in logs]

@app.post('/api/admin/documents/upload')
async def upload_document(file:UploadFile=File(...), s:Session=Depends(db), u=Depends(require_admin)):
    if not file.filename.lower().endswith('.pdf'): raise HTTPException(422,'Only PDF uploads are supported')
    raw=await file.read()
    if len(raw)>10*1024*1024: raise HTTPException(413,'Maximum file size is 10 MB')
    digest=hashlib.sha256(raw).hexdigest(); path=UPLOADS/f'{digest}.pdf'; path.write_bytes(raw)
    reader=PdfReader(str(path)); pages=[]
    for i,p in enumerate(reader.pages,1):
        txt=(p.extract_text() or '').strip()
        if txt: pages.append((i,txt))
    content='\n\n'.join(t for _,t in pages)
    if not content: raise HTTPException(422,'No extractable text found in PDF')
    match=re.search(r'\bIS\s*[0-9]{2,6}(?:\s*\([^)]*\))?(?::\s*[0-9]{4})?',content,re.I)
    d=Document(title=file.filename,standard_number=match.group(0) if match else None,category='Uploaded document',version='Uploaded',source_url='Local upload',source_type='User uploaded',status='CURRENT',content=content,content_hash=digest,verified=False)
    s.add(d); s.flush()
    for page,text in pages:
        for start in range(0,len(text),1200): s.add(Chunk(document_id=d.id,text=text[start:start+1200],page=page,section='Extracted PDF'))
    s.commit()
    return {'id':d.id,'title':d.title,'pages':len(pages),'chunks':len(d.content)//1200+1,'standard_number':d.standard_number,'verified':False}

@app.get('/api/admin/documents')
def admin_docs(s:Session=Depends(db),u=Depends(require_admin)):
    docs=list(s.scalars(select(Document).order_by(Document.id.desc())).all())
    return [{'id':d.id,'title':d.title,'standard_number':d.standard_number,'version':d.version,'status':d.status,'verified':d.verified,'source_type':d.source_type,'created_at':d.created_at.isoformat()} for d in docs]
