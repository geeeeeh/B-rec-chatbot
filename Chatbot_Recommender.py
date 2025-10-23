#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit 대화형 책 추천 챗봇 (카탈로그/API 미사용) — v2 (발굴 모드 추가)
- 사용자의 5개 핵심 입력 + '신간 범위' 필터를 받아 LLM에 붙여넣을 프롬프트를 생성합니다.
- '유명도 우선/균형/발굴 우선' 모드를 선택해 더 실험적인 후보를 받을 수 있습니다.
- 요청에 따라 하드코딩된 소규모 데모 목록으로 임시 추천도 제공합니다(운영 권장 X).

실행 방법
  $ streamlit run streamlit_chatbot_recommender.py
"""
from __future__ import annotations
import textwrap
from datetime import datetime
import streamlit as st
from typing import List, Tuple

RECENT_YEARS = 5
CURRENT_YEAR = datetime.utcnow().year

# ----------------------------
# 데모 추천(옵션) - 소규모 예시 + 유명도 점수(popularity 0~1)
# ----------------------------
# (title, author, year, tone, genres, popularity)
DEMO_DB: List[Tuple[str,str,int,str,List[str],float]] = [
    ("노인과 바다", "어니스트 헤밍웨이", 1952, "잔잔", ["소설", "고전"], 0.98),
    ("그리고 아무도 없었다", "아가사 크리스티", 1939, "스릴", ["미스터리", "소설"], 0.97),
    ("데미안", "헤르만 헤세", 1919, "진지", ["소설", "성장"], 0.96),
    ("나는 고양이로소이다", "나쓰메 소세키", 1905, "유머", ["소설", "고전"], 0.9),
    ("해리 포터와 마법사의 돌", "J.K. 롤링", 1997, "모험", ["판타지", "소설"], 0.99),
    ("사피엔스", "유발 하라리", 2011, "진지", ["논픽션", "역사"], 0.98),
    ("유혹하는 에세이", "알랭 드 보통", 2000, "잔잔", ["에세이"], 0.85),
    ("The Midnight Library", "Matt Haig", 2020, "잔잔", ["소설"], 0.9),
    ("Project Hail Mary", "Andy Weir", 2021, "스릴", ["SF", "소설"], 0.92),
    # 의도적 '발굴' 후보(덜 대중적일 수 있는 예시)
    ("나의 산책은 길에서 시작된다", "임의 작가A", 2018, "잔잔", ["에세이"], 0.3),
    ("도시의 낮은 별들", "임의 작가B", 2022, "진지", ["소설"], 0.25),
    ("바람이 그린 지도", "임의 작가C", 2023, "모험", ["소설", "여행"], 0.2),
]

# ----------------------------
# 점수화 유틸(데모용)
# ----------------------------

def _genre_overlap(user_genres: List[str], book_genres: List[str]) -> float:
    ug = set(g.lower() for g in user_genres)
    bg = set(g.lower() for g in book_genres)
    if not ug:
        return 0.2  # 장르 미입력 시 중립값
    return len(ug & bg) / max(1, len(ug))


def demo_recommend(prefs: dict, k: int = 5, mode: str = "famous", explore_strength: float = 0.6):
    """발굴 모드 반영 추천.
    mode: 'famous' | 'balanced' | 'discover'
    explore_strength: 0~1 (discover 모드에서 인기 반전 가중)
    """
    W_GENRE = 0.55
    W_TONE = 0.3
    W_RECENT = 0.15

    genres = prefs.get('genres', [])
    tone = prefs.get('tone')
    recent_only = prefs.get('recent_only', False)

    # 모드별 인기 가중치(가산/감산)
    if mode == 'famous':
        pop_alpha, pop_beta = 0.30, 0.00   # 인기 선호
    elif mode == 'balanced':
        pop_alpha, pop_beta = 0.15, 0.10   # 절충
    else:  # 'discover'
        pop_alpha, pop_beta = 0.00, explore_strength  # 비인기 선호(발굴 강화)

    scored = []
    for rec in DEMO_DB:
        title, author, year, btone, bgenres, popularity = rec
        if recent_only and year < (CURRENT_YEAR - RECENT_YEARS):
            continue

        s_genre = _genre_overlap(genres, bgenres)
        s_tone = 1.0 if (tone and tone == btone) else (0.5 if not tone else 0.2)
        s_recent = 1.0 if year >= (CURRENT_YEAR - RECENT_YEARS) else 0.5

        # 인기/발굴 조합 점수
        pop_score = pop_alpha * popularity + pop_beta * (1.0 - popularity)

        score = (W_GENRE*s_genre + W_TONE*s_tone + W_RECENT*s_recent) + pop_score

        why = []
        if s_genre > 0.0: why.append("장르 일치")
        if s_tone == 1.0: why.append("톤 일치")
        if recent_only: why.append("최근 5년 필터")
        if mode == 'discover':
            why.append("발굴 가중")
        elif mode == 'famous':
            why.append("유명도 가중")
        else:
            why.append("균형 가중")

        scored.append((rec, float(score), why))

    # 다양성: 같은 작가/같은 대표 장르 연속 과포화 방지(간단 페널티)
    scored.sort(key=lambda x: x[1], reverse=True)
    picked = []
    seen_authors = set()
    for rec, sc, why in scored:
        title, author, year, btone, bgenres, popularity = rec
        if author in seen_authors and len(picked) < k-1:
            continue
        picked.append((rec, sc, why))
        seen_authors.add(author)
        if len(picked) >= k:
            break
    return picked

# ----------------------------
# 프롬프트 생성
# ----------------------------

def build_prompt(genres:List[str], tone:str, avoid:List[str], liked_books:List[str], length_pref:str, recent_only:bool, mode:str, explore_strength:float) -> str:
    mode_text = {
        'famous': '유명도 높은 작품 우선',
        'balanced': '유명도와 발굴의 균형',
        'discover': f'발굴 우선(실험성 {int(explore_strength*100)}%)'
    }[mode]

    prompt = textwrap.dedent(f"""
    아래 사용자의 선호를 반영해 실제로 존재하는 책만 5권 이내로 추천해 주세요.
    - 모드: {mode_text}
    - 실수/환각 방지: 존재 불명/오탈자 제목 금지, 세부 수치(페이지/ISBN/가격) 추정 금지
    - 민감 콘텐츠는 '기피 요소'를 기준으로 제외
    - 각 추천에 2–3줄 근거(장르/톤/테마 중심, 스포일러 금지)
    - 다양성: 동일 작가/시리즈 과도 반복 금지
    - 언어 표기는 원제 병기 가능, 한글 응답
    - 최신성 필터: {'최근 5년만' if recent_only else '제한 없음'}

    [사용자 입력]
    • 선호 장르: {', '.join(genres) if genres else '(미입력)'}
    • 선호 톤: {tone or '(미입력)'}
    • 기피 요소: {', '.join(avoid) if avoid else '(없음)'}
    • 최근 좋아한 책(선택): {', '.join(liked_books) if liked_books else '(미입력)'}
    • 분량 느낌: {length_pref}
    """)
    return prompt.strip()

# ----------------------------
# Streamlit UI
# ----------------------------

st.set_page_config(page_title="대화형 책 추천 챗봇", page_icon="📚", layout="centered")
st.title("📚 대화형 책 추천 챗봇 (카탈로그/API 없이)")
st.caption("입력값으로 LLM 프롬프트를 만들고, 필요 시 데모 추천을 확인할 수 있어요. — v2 발굴 모드 포함")

with st.sidebar:
    st.header("입력")
    genres = st.multiselect(
        "선호 장르 (복수 선택)",
        options=["소설","미스터리","판타지","SF","에세이","논픽션","고전","성장","여행"],
        default=[],
        help="추천 재랭킹에 강하게 영향을 줍니다."
    )
    tone = st.selectbox(
        "선호 톤/분위기 (선택)",
        options=["", "잔잔","유머","진지","스릴","모험","따뜻함","어둡고 무거움"],
        index=0
    )
    avoid_raw = st.text_input(
        "기피 요소(쉼표 구분)",
        placeholder="폭력성, 고어, 노골적 로맨스 …"
    )
    avoid = [x.strip() for x in avoid_raw.split(',') if x.strip()]

    liked_toggle = st.checkbox("최근 좋아한 책 2–3권 입력(선택)", value=False)
    liked_books = []
    if liked_toggle:
        liked_raw = st.text_input("제목만 쉼표로 입력", placeholder="데미안, 사피엔스")
        liked_books = [x.strip() for x in liked_raw.split(',') if x.strip()]

    length_pref = st.radio("분량 느낌", ["짧게","보통","길게"], index=1, horizontal=True)
    recency = st.radio("신간 범위 필터", ["최근5년만","전체포함"], index=1, horizontal=True)
    recent_only = (recency == "최근5년만")

    st.markdown("---")
    mode = st.radio("추천 모드", ["유명도 우선","균형","발굴 우선"], index=0, help="발굴 모드에서는 덜 알려진 작품을 의도적으로 끌어올립니다.")
    explore_strength = st.slider("발굴 강도(Discover)", 0.0, 1.0, 0.6, 0.1, help="발굴 우선 모드에서 비인기 항목을 얼마나 가산할지")

    k = st.slider("표시할 추천 개수(데모)", min_value=3, max_value=10, value=5)

# 버튼 영역
col1, col2 = st.columns(2)
with col1:
    if st.button("🔧 프롬프트 생성"):
        mode_key = {"유명도 우선":"famous","균형":"balanced","발굴 우선":"discover"}[mode]
        prompt = build_prompt(genres, tone, avoid, liked_books, length_pref, recent_only, mode_key, explore_strength)
        st.subheader("LLM 프롬프트")
        st.code(prompt, language="markdown")
        st.session_state["_last_prompt"] = prompt

with col2:
    if st.button("🧪 데모 추천 보기"):
        mode_key = {"유명도 우선":"famous","균형":"balanced","발굴 우선":"discover"}[mode]
        prefs = {
            "genres": genres,
            "tone": tone if tone else None,
            "avoid": avoid,
            "liked_books": liked_books,
            "length_pref": length_pref,
            "recent_only": recent_only,
        }
        recs = demo_recommend(prefs, k=k, mode=mode_key, explore_strength=explore_strength)
        if not recs:
            st.warning("조건에 맞는 데모 추천이 없습니다. (필터/모드 조합을 조정해 보세요)")
        else:
            st.subheader("데모 추천 결과 (하드코딩 목록)")
            for i, (rec, score, why) in enumerate(recs, start=1):
                title, author, year, btone, bgenres, popularity = rec
                with st.container(border=True):
                    st.markdown(f"**[{i}] {title}** — {author} ({year})")
                    st.caption(
                        f"톤: {btone} | 장르: {', '.join(bgenres)} | 유명도: {popularity:.2f} | 점수: {score:.2f}"
                    )
                    if why:
                        st.write("이유: ", ", ".join(why))

# 하단 도움말
st.divider()
st.info("페이지 수는 판/번역/판형에 따라 달라 정확값 제공이 어려워 '분량 느낌'으로 대신 받습니다. 필요 시 서점/도서관 메타로 보강하세요.")
