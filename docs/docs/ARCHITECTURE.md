# BIS Intelligence Architecture

## Core principle
Evidence first → AI second → workflow third.

## Frontend
Next.js/React + TypeScript + Tailwind-style utility classes + Framer Motion.

## Backend
FastAPI service with typed request/response contracts.

## Data
PostgreSQL + pgvector-ready schema. Demo JSON is isolated from production data.

## RAG
Document ingestion → extraction → cleaning → metadata → semantic chunking → embeddings → hybrid retrieval → reranking → evidence selection → LLM synthesis → citation validation.

## Trust
The model is not the source of truth. Low-evidence queries should be refused/qualified.

## Production integration
The prototype must not claim privileged BIS API access. Authorized BIS repositories/APIs can be added through provider interfaces later.

## SIH hero flow
Product description → standard candidates → why match → evidence → compliance roadmap → checklist.
