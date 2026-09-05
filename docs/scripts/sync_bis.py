#!/usr/bin/env python3
"""Download and index public BIS web/PDF material into the local BIS database.

This is intentionally a conservative official-source crawler. It only starts from
URLs in data/bis_official/source_registry.json and follows links on BIS domains.
It stores extracted text, not a mirror of the BIS site. Run it periodically because
BIS standards, amendments and QCOs change.
"""
import argparse, hashlib, json, re, sqlite3, time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "backend" / "bis_intelligence.db"
REG = ROOT / "data" / "bis_official" / "source_registry.json"
USER_AGENT = "BIS-Intelligence-Research-Bot/1.0 (official BIS sources only)"

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.parts=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower()=="a":
            d=dict(attrs); href=d.get("href")
            if href: self.links.append(href)
    def handle_data(self, data): self.parts.append(data)

def fetch(url, timeout=30):
    req=Request(url, headers={"User-Agent":USER_AGENT,"Accept":"text/html,application/pdf,*/*"})
    with urlopen(req, timeout=timeout) as r:
        return r.headers.get_content_type(), r.read()

def clean_html(raw):
    p=LinkParser(); p.feed(raw.decode("utf-8", errors="ignore"))
    text=re.sub(r"\\s+", " ", " ".join(p.parts)).strip()
    return text, p.links

def chunks(text, size=1400, overlap=180):
    out=[]; start=0
    while start < len(text):
        end=min(len(text),start+size); piece=text[start:end].strip()
        if piece: out.append(piece)
        if end>=len(text): break
        start=max(end-overlap,start+1)
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--max-pages",type=int,default=500); ap.add_argument("--max-pdfs",type=int,default=100); ap.add_argument("--delay",type=float,default=0.5); ap.add_argument("--download-pdfs",action="store_true"); args=ap.parse_args()
    reg=json.loads(REG.read_text(encoding="utf-8")); seeds=[x["url"] for x in reg["sources"]]
    if not DB.exists(): raise SystemExit(f"Database not found: {DB}. Start backend once first.")
    con=sqlite3.connect(DB); cur=con.cursor()
    q=list(dict.fromkeys(seeds)); seen=set(); pdfs=0; pages=0
    while q and pages < args.max_pages:
        url=q.pop(0)
        if url in seen: continue
        p=urlparse(url)
        if p.netloc not in {"www.bis.gov.in","bis.gov.in"}: continue
        seen.add(url)
        try: ctype, body=fetch(url)
        except Exception as e: print("SKIP",url,e); continue
        time.sleep(args.delay)
        if ctype=="application/pdf" or url.lower().endswith(".pdf"):
            if not args.download_pdfs or pdfs>=args.max_pdfs: continue
            tmp=ROOT/"data"/"bis_official"/"downloads"; tmp.mkdir(parents=True,exist_ok=True)
            path=tmp/(hashlib.sha1(url.encode()).hexdigest()+".pdf"); path.write_bytes(body)
            try:
                reader=PdfReader(str(path)); text="\\n".join((pg.extract_text() or "") for pg in reader.pages)
            except Exception as e: print("PDFERR",url,e); continue
            title=url.rsplit("/",1)[-1]
            pdfs+=1
        else:
            text, links=clean_html(body); title=urlparse(url).path.strip("/") or "BIS Official"
            for href in links:
                nxt=urljoin(url,href).split("#",1)[0]
                if urlparse(nxt).netloc in {"www.bis.gov.in","bis.gov.in"} and (nxt.startswith("https://") or nxt.startswith("http://")):
                    if nxt not in seen and nxt not in q: q.append(nxt)
        if len(text)<80: continue
        standard=None
        m=re.search(r"\bIS\s*[0-9]{2,6}(?:\s*\([^)]{1,30}\))?(?::|-)[0-9]{4}\b", text, re.I)
        if m: standard=re.sub(r"\\s+"," ",m.group(0)).strip()
        h=hashlib.sha256((url+text[:100000]).encode()).hexdigest()
        row=cur.execute("SELECT id FROM documents WHERE content_hash=?",(h,)).fetchone()
        if not row:
            cur.execute("INSERT INTO documents(title,standard_number,category,version,source_url,source_type,status,content,content_hash,verified) VALUES(?,?,?,?,?,?,?,?,?,?)",(title,standard,"BIS Official Web", "Live crawl",url,"BIS Official", "CURRENT",text,h,True))
            did=cur.lastrowid
            for i,piece in enumerate(chunks(text)): cur.execute("INSERT INTO chunks(document_id,text,page,section) VALUES(?,?,?,?)",(did,piece,1,f"Official BIS crawl {i+1}"))
            con.commit()
        pages+=1
        if pages%25==0: print(f"Indexed {pages} pages; queue={len(q)}")
    con.close(); print(f"Done. Indexed/checked {pages} pages and {pdfs} PDFs.")

if __name__=="__main__": main()
