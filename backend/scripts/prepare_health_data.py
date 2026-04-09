# 원본 Excel 파일 정제하고 나서 csv 파일로 변환해준다
# 사실상 추가할 문서 없으면 딱히 필요없긴 함

from __future__ import annotations

from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / 'data' / 'raw'
OUT_DIR = BASE_DIR / 'data' / 'processed'
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_FILE = RAW_DIR / 'chunk 모음 (3).xlsx'
META_FILE = RAW_DIR / 'metadata 모음 (1).xlsx'
FAQ_FILE = RAW_DIR / '자주하는 질문 모음 (1).xlsx'


def normalize_doc_id(value: str) -> str:
    return str(value).strip().replace('KCDA_', 'KDCA_').replace(' ', '_')


def ensure_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f'파일이 없습니다: {path}')


def clean_chunks(df: pd.DataFrame) -> pd.DataFrame:
    expected = [
        'chunk_id', 'doc_id', 'source_org', 'title', 'topic',
        'sub_topic', 'chunk_index', 'chunk_intent', 'chunk_text'
    ]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f'chunks 파일 컬럼 누락: {missing}')

    df = df[expected].copy()
    df['chunk_id'] = df['chunk_id'].astype(str).str.strip().str.replace('KCDA_', 'KDCA_', regex=False)
    df['doc_id'] = df['doc_id'].astype(str).map(normalize_doc_id)
    for col in ['source_org', 'title', 'topic', 'sub_topic', 'chunk_intent']:
        df[col] = df[col].astype(str).str.strip()
    df['chunk_text'] = df['chunk_text'].astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
    df['chunk_index'] = pd.to_numeric(df['chunk_index'], errors='raise').astype(int)

    if df['chunk_id'].duplicated().any():
        dupes = df.loc[df['chunk_id'].duplicated(keep=False), 'chunk_id'].tolist()
        raise ValueError(f'중복 chunk_id 발견: {dupes[:10]}')

    # 문서별 chunk_index 연속성 확인
    bad_docs = []
    for doc_id, group in df.groupby('doc_id'):
        indexes = sorted(group['chunk_index'].tolist())
        expected_indexes = list(range(1, len(indexes) + 1))
        if indexes != expected_indexes:
            bad_docs.append((doc_id, indexes))
    if bad_docs:
        raise ValueError(f'chunk_index가 연속이 아닌 문서가 있습니다: {bad_docs[:5]}')

    return df


def clean_documents(df: pd.DataFrame) -> pd.DataFrame:
    expected = [
        'doc_id', 'title', 'source_org', 'source_url',
        'topic', 'sub_topic', 'trust_level', 'collected_date'
    ]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f'documents 파일 컬럼 누락: {missing}')

    df = df[expected].copy()
    df['doc_id'] = df['doc_id'].astype(str).map(normalize_doc_id)
    for col in ['title', 'source_org', 'source_url', 'topic', 'sub_topic']:
        df[col] = df[col].astype(str).str.strip()
    df['trust_level'] = df['trust_level'].astype(str).str.strip().str.lower()
    df['collected_date'] = pd.to_datetime(df['collected_date']).dt.strftime('%Y-%m-%d')

    if df['doc_id'].duplicated().any():
        dupes = df.loc[df['doc_id'].duplicated(keep=False), 'doc_id'].tolist()
        raise ValueError(f'중복 doc_id 발견: {dupes}')

    return df


def clean_faqs(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        '자주 묻는 질문': 'question',
        '그에 대한 응답': 'answer',
    }
    df = df.rename(columns=rename_map).copy()

    expected = ['doc_id', 'title', 'question', 'answer']
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f'faq 파일 컬럼 누락: {missing}')

    df = df[expected].copy()
    df[['doc_id', 'title']] = df[['doc_id', 'title']].ffill()
    df['doc_id'] = df['doc_id'].astype(str).map(normalize_doc_id)
    df['title'] = df['title'].astype(str).str.strip()
    df['question'] = df['question'].astype(str).str.strip()
    df['answer'] = df['answer'].astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()

    invalid_values = {'', '(없음)', 'nan', 'None'}
    df = df[~df['question'].isin(invalid_values)]
    df = df[~df['answer'].isin(invalid_values)]
    df = df.reset_index(drop=True)
    df['faq_index'] = df.groupby('doc_id').cumcount() + 1
    df['faq_id'] = df.apply(lambda r: f"{r['doc_id']}_FAQ_{int(r['faq_index']):02d}", axis=1)
    return df[['faq_id', 'doc_id', 'title', 'question', 'answer']]


def main() -> None:
    for path in [CHUNK_FILE, META_FILE, FAQ_FILE]:
        ensure_exists(path)

    chunks = clean_chunks(pd.read_excel(CHUNK_FILE))
    documents = clean_documents(pd.read_excel(META_FILE))
    faqs = clean_faqs(pd.read_excel(FAQ_FILE))

    chunk_doc_ids = set(chunks['doc_id'])
    doc_ids = set(documents['doc_id'])
    faq_doc_ids = set(faqs['doc_id'])

    if not chunk_doc_ids.issubset(doc_ids):
        raise ValueError(f'chunks에만 존재하는 doc_id: {sorted(chunk_doc_ids - doc_ids)}')
    if not faq_doc_ids.issubset(doc_ids):
        raise ValueError(f'faqs에만 존재하는 doc_id: {sorted(faq_doc_ids - doc_ids)}')

    documents.to_csv(OUT_DIR / 'documents_clean.csv', index=False, encoding='utf-8-sig')
    chunks.to_csv(OUT_DIR / 'chunks_clean.csv', index=False, encoding='utf-8-sig')
    faqs.to_csv(OUT_DIR / 'faqs_clean.csv', index=False, encoding='utf-8-sig')

    print('CSV 생성 완료')
    print(f' - documents: {len(documents)}건')
    print(f' - chunks:    {len(chunks)}건')
    print(f' - faqs:      {len(faqs)}건')
    print(f'저장 위치: {OUT_DIR}')


if __name__ == '__main__':
    main()
