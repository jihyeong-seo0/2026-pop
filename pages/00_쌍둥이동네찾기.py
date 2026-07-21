import re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="지역별 인구 구조", page_icon="📊", layout="wide")

CSV_PATH = "202606_202606_연령별인구현황_월간.csv"  # app.py와 같은 폴더에 있어야 합니다


@st.cache_data
def load_data(path):
    df = pd.read_csv(path, encoding="cp949")

    # 행정구역 이름에서 뒤쪽 코드값 "(1234567890)" 제거한 표시용 컬럼 생성
    df["지역명"] = df["행정구역"].str.replace(r"\s*\(\d+\)\s*$", "", regex=True).str.strip()

    # 행정구역/지역명을 제외한 모든 컬럼은 숫자 컬럼이므로 콤마 제거 후 숫자형으로 일괄 변환
    value_cols = [c for c in df.columns if c not in ("행정구역", "지역명")]
    for col in value_cols:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(",", "", regex=False), errors="coerce"
        )

    # "년월_성별_나이세" 패턴 컬럼만 따로 추출 (계/남/여 각각 0세~100세이상)
    age_pattern = re.compile(r"^(\d{4}년\d{2}월)_(계|남|여)_(\d+)세$|^(\d{4}년\d{2}월)_(계|남|여)_(100세 이상)$")

    age_cols = []
    for col in value_cols:
        m = age_pattern.match(col)
        if m:
            if m.group(1):  # 일반 나이
                month, gender, age = m.group(1), m.group(2), int(m.group(3))
            else:  # 100세 이상
                month, gender, age = m.group(4), m.group(5), 100
            age_cols.append((col, month, gender, age))

    age_df = pd.DataFrame(age_cols, columns=["컬럼명", "년월", "성별", "나이"])
    return df, age_df


@st.cache_data
def compute_similarity(df, age_meta, month, target_region, top_n=5):
    """선택 지역과 전국 지역들의 연령별 인구 '비율(구조)'을 코사인 유사도로 비교"""
    sub = age_meta[(age_meta["년월"] == month) & (age_meta["성별"] == "계")].sort_values("나이")
    cols = sub["컬럼명"].tolist()
    total_col = f"{month}_계_총인구수"

    mat = df[cols].to_numpy(dtype=float)
    totals = df[total_col].to_numpy(dtype=float)
    valid = totals > 0  # 인구 0인 지역은 비율 계산 불가하므로 제외

    prop = np.zeros_like(mat)
    prop[valid] = mat[valid] / totals[valid, None]

    target_idx = df.index[df["지역명"] == target_region]
    if len(target_idx) == 0:
        return pd.DataFrame(), None
    target_idx = target_idx[0]
    target_vec = prop[target_idx]

    norms = np.linalg.norm(prop, axis=1)
    target_norm = np.linalg.norm(target_vec)
    with np.errstate(divide="ignore", invalid="ignore"):
        sims = (prop @ target_vec) / (norms * target_norm + 1e-12)

    result = pd.DataFrame({
        "지역명": df["지역명"],
        "유사도": sims,
        "총인구수": totals,
    })
    result = result[valid & (result["지역명"] != target_region)]
    top = result.sort_values("유사도", ascending=False).head(top_n).reset_index(drop=True)

    ages = sub["나이"].tolist()
    return top, {"ages": ages, "prop_matrix": prop, "cols": cols}


try:
    df, age_meta = load_data(CSV_PATH)
except FileNotFoundError:
    st.error(f"'{CSV_PATH}' 파일을 찾을 수 없습니다. app.py와 같은 폴더에 CSV를 넣어주세요.")
    st.stop()

st.title("📊 지역별 인구 구조 보기")
st.caption("행정안전부 연령별 인구현황 데이터를 기반으로 선택한 지역의 연령별 인구 구조를 보여줍니다.")

months = sorted(age_meta["년월"].unique())

with st.sidebar:
    st.header("조회 조건")

    selected_month = st.selectbox("기준 년월", months, index=len(months) - 1)

    region_list = df["지역명"].tolist()
    selected_regions = st.multiselect(
        "지역 선택 (직접 입력해서 검색 가능)",
        options=region_list,
        default=[region_list[0]] if region_list else [],
        help="목록을 클릭하거나, 지역명을 타이핑해서 검색할 수 있습니다.",
    )

    gender_labels = {"계": "전체", "남": "남성", "여": "여성"}
    selected_genders = st.multiselect(
        "성별",
        options=list(gender_labels.keys()),
        default=["계"],
        format_func=lambda g: gender_labels[g],
    )

    show_table = st.checkbox("데이터 표 함께 보기", value=False)

    st.divider()
    st.header("유사 지역 찾기")
    similarity_target = st.selectbox(
        "기준 지역 (전국에서 가장 비슷한 Top 5를 찾습니다)",
        options=region_list,
        index=region_list.index(selected_regions[0]) if selected_regions else 0,
        help="읍면동 단위를 포함한 전국 모든 행정구역을 대상으로 비교합니다.",
    )

if not selected_regions:
    st.info("왼쪽 사이드바에서 지역을 하나 이상 선택해주세요.")
    st.stop()

if not selected_genders:
    st.info("왼쪽 사이드바에서 성별을 하나 이상 선택해주세요.")
    st.stop()

# ---------- 1. 연령별 인구 구조 꺾은선 그래프 ----------
sub_meta = age_meta[age_meta["년월"] == selected_month].sort_values("나이")

fig = go.Figure()

for region in selected_regions:
    row = df[df["지역명"] == region]
    if row.empty:
        continue
    row = row.iloc[0]

    for gender in selected_genders:
        gender_meta = sub_meta[sub_meta["성별"] == gender]
        ages = gender_meta["나이"].tolist()
        pops = [row[c] for c in gender_meta["컬럼명"]]

        label = f"{region} · {gender_labels[gender]}"
        fig.add_trace(
            go.Scatter(
                x=ages,
                y=pops,
                mode="lines",
                name=label,
                hovertemplate="나이: %{x}세<br>인구수: %{y:,.0f}명<extra>" + label + "</extra>",
            )
        )

fig.update_layout(
    title=f"{selected_month} 연령별 인구 구조",
    xaxis_title="나이",
    yaxis_title="인구수 (명)",
    hovermode="x unified",
    legend_title="지역 · 성별",
    height=550,
)
fig.update_yaxes(tickformat=",")

st.plotly_chart(fig, use_container_width=True)

# 요약 지표
st.subheader("요약")
cols = st.columns(len(selected_regions))
for i, region in enumerate(selected_regions):
    row = df[df["지역명"] == region]
    if row.empty:
        continue
    row = row.iloc[0]
    total_col = f"{selected_month}_계_총인구수"
    total_pop = row[total_col] if total_col in row else None
    with cols[i]:
        st.metric(region, f"{total_pop:,.0f}명" if pd.notna(total_pop) else "N/A")

if show_table:
    st.subheader("원본 데이터 (선택 지역)")
    st.dataframe(df[df["지역명"].isin(selected_regions)])

# ---------- 2. 전국 유사 지역 Top 5 ----------
st.divider()
st.header(f"🔍 '{similarity_target}'과(와) 인구구조가 가장 비슷한 지역 Top 5")
st.caption("절대 인구수가 아니라 연령별 인구 '비율'의 모양(코사인 유사도)을 기준으로 비교합니다. 읍면동 포함 전국 모든 행정구역이 대상입니다.")

top5, extra = compute_similarity(df, age_meta, selected_month, similarity_target, top_n=5)

if top5.empty or extra is None:
    st.warning("유사 지역을 계산할 수 없습니다. (인구수가 0이거나 데이터가 없는 지역일 수 있습니다)")
else:
    # 2-1. 유사도 막대 그래프
    bar_fig = go.Figure(
        go.Bar(
            x=top5["유사도"],
            y=top5["지역명"],
            orientation="h",
            text=[f"{v:.4f}" for v in top5["유사도"]],
            textposition="outside",
            marker_color="#5ecdff",
        )
    )
    bar_fig.update_layout(
        title="유사도 점수 (1에 가까울수록 구조가 비슷함)",
        xaxis_title="코사인 유사도",
        yaxis=dict(autorange="reversed"),
        height=320,
    )
    st.plotly_chart(bar_fig, use_container_width=True)

    # 2-2. 연령별 인구 비율(%) 곡선 비교 - 기준 지역 vs Top5
    ages = extra["ages"]
    prop = extra["prop_matrix"]

    shape_fig = go.Figure()

    target_idx = df.index[df["지역명"] == similarity_target][0]
    shape_fig.add_trace(
        go.Scatter(
            x=ages,
            y=prop[target_idx] * 100,
            mode="lines",
            name=f"★ {similarity_target} (기준)",
            line=dict(width=4, color="black"),
        )
    )

    for _, r in top5.iterrows():
        idx = df.index[df["지역명"] == r["지역명"]][0]
        shape_fig.add_trace(
            go.Scatter(
                x=ages,
                y=prop[idx] * 100,
                mode="lines",
                name=f"{r['지역명']} (유사도 {r['유사도']:.3f})",
                line=dict(width=2, dash="dot"),
            )
        )

    shape_fig.update_layout(
        title=f"{selected_month} 연령별 인구 비율(%) 비교 - 기준 지역 vs Top 5",
        xaxis_title="나이",
        yaxis_title="해당 연령 인구 비율 (%)",
        hovermode="x unified",
        height=550,
    )
    st.plotly_chart(shape_fig, use_container_width=True)

    st.subheader("Top 5 상세")
    display_top5 = top5.copy()
    display_top5["유사도"] = display_top5["유사도"].map(lambda v: f"{v:.4f}")
    display_top5["총인구수"] = display_top5["총인구수"].map(lambda v: f"{v:,.0f}명")
    st.dataframe(display_top5, use_container_width=True, hide_index=True)
