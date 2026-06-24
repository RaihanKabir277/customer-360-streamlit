import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import time
from databricks import sql

# ════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Customer 360 Profile",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ════════════════════════════════════════════════════════════════
# DARK THEME STYLING (matches Databricks dashboard look)
# ════════════════════════════════════════════════════════════════
st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
    div[data-testid="stMetric"] {
        background-color: #1A1D24;
        border: 1px solid #2D3139;
        padding: 15px;
        border-radius: 10px;
    }
    div[data-testid="stMetricLabel"] { color: #9CA3AF; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #1A1D24;
        border-radius: 8px;
        padding: 8px 16px;
    }
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
# DATABRICKS CONNECTION
# ════════════════════════════════════════════════════════════════
@st.cache_resource
def get_connection():
    return sql.connect(
        server_hostname = st.secrets["DATABRICKS_HOST"],
        http_path       = st.secrets["DATABRICKS_HTTP_PATH"],
        access_token    = st.secrets["DATABRICKS_TOKEN"]
    )

@st.cache_data(ttl=600, show_spinner=False)
def run_query(query: str) -> pd.DataFrame:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query)
    cols = [d[0] for d in cursor.description]
    data = cursor.fetchall()
    cursor.close()
    return pd.DataFrame(data, columns=cols)

GREEN  = "#00BC8C"
RED    = "#E74C3C"
BLUE   = "#3498DB"
ORANGE = "#F39C12"

# ════════════════════════════════════════════════════════════════
# GENIE CONVERSATION API — direct backend integration
# Genie Space ID extracted from your room URL:
# .../genie/rooms/01f169470bfb1fd5b782cf196674831d?o=...
# ════════════════════════════════════════════════════════════════
GENIE_SPACE_ID = "01f169470bfb1fd5b782cf196674831d"

def _genie_headers():
    return {
        "Authorization": f"Bearer {st.secrets['DATABRICKS_TOKEN']}",
        "Content-Type": "application/json"
    }

def _genie_base_url():
    host = st.secrets["DATABRICKS_HOST"]
    return f"https://{host}/api/2.0/genie/spaces/{GENIE_SPACE_ID}"

def genie_start_conversation(question: str):
    """Starts a new Genie conversation with the first question."""
    url = f"{_genie_base_url()}/start-conversation"
    resp = requests.post(url, headers=_genie_headers(),
                         json={"content": question}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["conversation_id"], data["message_id"]

def genie_continue_conversation(conversation_id: str, question: str):
    """Sends a follow-up question in an existing Genie conversation."""
    url = f"{_genie_base_url()}/conversations/{conversation_id}/messages"
    resp = requests.post(url, headers=_genie_headers(),
                         json={"content": question}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["message_id"]

def genie_poll_message(conversation_id: str, message_id: str,
                        timeout_seconds: int = 60):
    """Polls Genie until the message finishes processing, returns final state."""
    url = f"{_genie_base_url()}/conversations/{conversation_id}/messages/{message_id}"
    start = time.time()
    while time.time() - start < timeout_seconds:
        resp = requests.get(url, headers=_genie_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            return data
        time.sleep(1.5)
    return {"status": "TIMEOUT"}

def genie_get_query_result(conversation_id: str, message_id: str, attachment_id: str):
    """Fetches tabular query result data if Genie ran a SQL query."""
    url = (f"{_genie_base_url()}/conversations/{conversation_id}"
           f"/messages/{message_id}/attachments/{attachment_id}/query-result")
    resp = requests.get(url, headers=_genie_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()

def genie_extract_answer(message_data: dict):
    """
    Parses a completed Genie message into (text_answer, dataframe_or_None).
    Genie messages can contain text attachments and/or query attachments.
    """
    text_parts = []
    df = None

    attachments = message_data.get("attachments", [])
    conv_id = message_data.get("conversation_id")
    msg_id  = message_data.get("id") or message_data.get("message_id")

    for att in attachments:
        if "text" in att:
            text_parts.append(att["text"].get("content", ""))
        elif "query" in att:
            q = att["query"]
            desc = q.get("description", "")
            if desc:
                text_parts.append(desc)
            att_id = att.get("attachment_id")
            if att_id and conv_id and msg_id:
                try:
                    result = genie_get_query_result(conv_id, msg_id, att_id)
                    rows = result.get("statement_response", {}) \
                                 .get("result", {}).get("data_array", [])
                    cols_meta = result.get("statement_response", {}) \
                                       .get("manifest", {}) \
                                       .get("schema", {}).get("columns", [])
                    col_names = [c["name"] for c in cols_meta] if cols_meta else None
                    if rows:
                        df = pd.DataFrame(rows, columns=col_names)
                except Exception:
                    pass

    answer_text = "\n\n".join([t for t in text_parts if t]) or "✅ Query completed."
    return answer_text, df

# ════════════════════════════════════════════════════════════════
# SIDEBAR — NAVIGATION
# ════════════════════════════════════════════════════════════════
st.sidebar.title("🏦 Customer 360 Profile")
st.sidebar.caption("Enterprise Banking Data Platform · Databricks")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigate",
    [
        "📋 Customer 360",
        "🤖 Customer Summary",
        "📊 Customer Segmentation",
        "🎯 Product Recommendations"
    ]
)

st.sidebar.divider()
st.sidebar.markdown("**Built with:**")
st.sidebar.markdown("Databricks · Delta Lake · Unity Catalog · Streamlit")
st.sidebar.markdown("[📁 View source on GitHub](https://github.com/RaihanKabir277/customer-360-databricks)")

# ════════════════════════════════════════════════════════════════
# LOAD CUSTOMER LIST ONCE (used across pages)
# ════════════════════════════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)
def get_customer_list():
    return run_query("""
        SELECT customer_id, full_name, city
        FROM customer_360.gold.customer_360
        WHERE total_transactions > 0
          AND total_sessions > 0
        ORDER BY full_name
        LIMIT 2000
    """)

# ════════════════════════════════════════════════════════════════
# PAGE 1 — CUSTOMER 360 (Individual Profile)
# ════════════════════════════════════════════════════════════════
if page == "📋 Customer 360":
    st.title("Customer 360 Profile")
    st.caption("Page 1 of 4 · Customer_360")

    customers = get_customer_list()
    selected = st.selectbox(
        "🔍 Customer ID",
        options=customers["customer_id"].tolist(),
        format_func=lambda x: f"{x} — {customers.loc[customers['customer_id']==x, 'full_name'].values[0]}",
        key="page1_customer"
    )

    if selected:
        with st.spinner("Loading customer profile..."):
            cust = run_query(f"""
                SELECT * FROM customer_360.gold.customer_360
                WHERE customer_id = '{selected}'
            """).iloc[0]

        # ── 6 KPI cards ──────────────────────────────────────────
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total Balance",    f"${cust['total_balance']:,.0f}")
        c2.metric("Loan Exposure",    f"${cust['total_loan_amount']:,.0f}")
        c3.metric("Credit Score",     f"{int(cust['credit_score'])}")
        c4.metric("Monthly Spend",    f"${cust['avg_monthly_spending']:,.0f}")
        c5.metric("Engagement Score", f"{int(cust['engagement_score'])}")
        c6.metric("Churn Risk Score", f"{int(cust['churn_risk_score'])}")

        st.caption(f"👤 {cust['full_name']} · {cust['city']}")
        st.divider()

        # ── Row 1: Product Holdings | Monthly Spending ──────────
        col_l, col_r = st.columns(2)

        with col_l:
            holdings = run_query(f"""
                SELECT product_type, amount
                FROM customer_360.gold.product_holdings
                WHERE customer_id = '{selected}'
                  AND amount IS NOT NULL
                ORDER BY sort_order
            """)
            if not holdings.empty:
                fig = px.bar(holdings, x="amount", y="product_type",
                            orientation="h", title="Product Holdings",
                            color_discrete_sequence=[BLUE])
                fig.update_layout(template="plotly_dark",
                                  plot_bgcolor="#1A1D24",
                                  paper_bgcolor="#1A1D24", height=350)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No product holdings data available")

        with col_r:
            spending = run_query(f"""
                SELECT year_month, total_spending
                FROM customer_360.gold.monthly_spending
                WHERE customer_id = '{selected}'
                ORDER BY year_month
            """)
            if not spending.empty:
                fig = px.line(spending, x="year_month", y="total_spending",
                             title="Monthly Spending", markers=True,
                             color_discrete_sequence=[GREEN])
                fig.update_layout(template="plotly_dark",
                                  plot_bgcolor="#1A1D24",
                                  paper_bgcolor="#1A1D24", height=350)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No spending history available")

        # ── Row 2: Channel Usage | Churn Risk Trend ─────────────
        col_l2, col_r2 = st.columns(2)

        with col_l2:
            channels = run_query(f"""
                SELECT channel, session_pct
                FROM customer_360.gold.channel_usage
                WHERE customer_id = '{selected}'
                ORDER BY sessions DESC
            """)
            if not channels.empty:
                fig = px.bar(channels, x="session_pct", y="channel",
                            orientation="h", title="Channel Usage %",
                            color_discrete_sequence=[BLUE])
                fig.update_layout(template="plotly_dark",
                                  plot_bgcolor="#1A1D24",
                                  paper_bgcolor="#1A1D24", height=300)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No digital activity data available")

        with col_r2:
            churn = run_query(f"""
                SELECT year_month, monthly_churn_risk_score
                FROM customer_360.gold.churn_risk_monthly
                WHERE customer_id = '{selected}'
                ORDER BY year_month
            """)
            if not churn.empty:
                fig = px.line(churn, x="year_month", y="monthly_churn_risk_score",
                             title="Churn Risk Trend", markers=True,
                             color_discrete_sequence=[RED])
                fig.update_layout(template="plotly_dark",
                                  plot_bgcolor="#1A1D24",
                                  paper_bgcolor="#1A1D24", height=300)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No payment history available")

        st.divider()

        # ── Activity Feed ────────────────────────────────────────
        st.subheader("Activity Feed")
        activity = run_query(f"""
            SELECT when_label, event_description, amount,
                   direction, channel, event_status,
                   event_category, event_type, event_datetime
            FROM customer_360.gold.activity_feed
            WHERE customer_id = '{selected}'
            ORDER BY
              CASE WHEN amount IS NULL THEN 1 ELSE 0 END ASC,
              event_datetime DESC
            LIMIT 30
        """)
        if not activity.empty:
            st.dataframe(activity, use_container_width=True, hide_index=True)
        else:
            st.info("No activity recorded for this customer")

# ════════════════════════════════════════════════════════════════
# PAGE 2 — CUSTOMER SUMMARY (AI-Powered Narrative)
# ════════════════════════════════════════════════════════════════
elif page == "🤖 Customer Summary":
    st.title("Customer 360 Profile")
    st.caption("Page 2 of 4 · Customer_Summary")

    st.info(
        "🤖 **AI-Powered Customer Briefing** — Search any customer ID below "
        "to get a complete A-Z summary including risk flags and recommended "
        "banker actions, generated automatically from live banking data.",
        icon="🤖"
    )

    # ── Genie AI Chat — embedded, no visitor login required ──────
    with st.expander("💬 Chat with Customer 360 AI Assistant (powered by Databricks Genie)", expanded=False):

        if "genie_conversation_id" not in st.session_state:
            st.session_state.genie_conversation_id = None
        if "genie_messages" not in st.session_state:
            st.session_state.genie_messages = []

        # Display chat history
        for msg in st.session_state.genie_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("dataframe") is not None:
                    st.dataframe(msg["dataframe"], use_container_width=True, hide_index=True)

        # Chat input
        user_question = st.chat_input(
            "Ask about any customer, e.g. 'Which customers have the highest churn risk?'"
        )

        if user_question:
            st.session_state.genie_messages.append(
                {"role": "user", "content": user_question, "dataframe": None}
            )
            with st.chat_message("user"):
                st.markdown(user_question)

            with st.chat_message("assistant"):
                with st.spinner("🧠 Genie is thinking..."):
                    try:
                        if st.session_state.genie_conversation_id is None:
                            conv_id, msg_id = genie_start_conversation(user_question)
                            st.session_state.genie_conversation_id = conv_id
                        else:
                            conv_id = st.session_state.genie_conversation_id
                            msg_id = genie_continue_conversation(conv_id, user_question)

                        result = genie_poll_message(conv_id, msg_id)
                        status = result.get("status")

                        if status == "COMPLETED":
                            answer_text, answer_df = genie_extract_answer(result)
                        elif status == "TIMEOUT":
                            answer_text, answer_df = (
                                "⏳ Genie took too long to respond. Please try again.", None
                            )
                        else:
                            answer_text, answer_df = (
                                f"⚠️ Genie could not complete this request ({status}).", None
                            )

                    except requests.exceptions.HTTPError as e:
                        answer_text, answer_df = (
                            f"❌ Connection error reaching Genie API: {e}", None
                        )
                    except Exception as e:
                        answer_text, answer_df = (
                            f"❌ Unexpected error: {e}", None
                        )

                    st.markdown(answer_text)
                    if answer_df is not None:
                        st.dataframe(answer_df, use_container_width=True, hide_index=True)

            st.session_state.genie_messages.append(
                {"role": "assistant", "content": answer_text, "dataframe": answer_df}
            )

        if st.button("🔄 Start New Conversation"):
            st.session_state.genie_conversation_id = None
            st.session_state.genie_messages = []
            st.rerun()

    customers = get_customer_list()
    selected = st.selectbox(
        "🔍 Search Customer by ID or Name",
        options=customers["customer_id"].tolist(),
        format_func=lambda x: f"{x} — {customers.loc[customers['customer_id']==x, 'full_name'].values[0]}",
        key="page2_customer"
    )

    if selected:
        with st.spinner("Generating customer briefing..."):
            row = run_query(f"""
                SELECT *
                FROM customer_360.gold.customer_full_summary
                WHERE customer_id = '{selected}'
            """).iloc[0]

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Customer Name",    row["full_name"])
        c2.metric("Credit Score",     int(row["credit_score"]))
        c3.metric("Total Balance",    f"${row['total_balance']:,.0f}")
        c4.metric("Engagement Score", int(row["engagement_score"]))
        c5.metric("Churn Risk Score", int(row["churn_risk_score"]))

        st.divider()
        st.subheader("Complete Customer Summary")
        st.markdown(
            f"""<div style="background-color:#1A1D24; padding:24px;
            border-radius:10px; border:1px solid #2D3139; white-space:pre-wrap;
            font-family:monospace; font-size:14px; line-height:1.6;">
            {row['customer_summary_text']}
            </div>""",
            unsafe_allow_html=True
        )

# ════════════════════════════════════════════════════════════════
# PAGE 3 — CUSTOMER SEGMENTATION (Portfolio View)
# ════════════════════════════════════════════════════════════════
elif page == "📊 Customer Segmentation":
    st.title("Customer 360 Profile")
    st.caption("Page 3 of 4 · Customer_Segmentation")

    with st.spinner("Loading segmentation data..."):
        seg_overview = run_query("""
            SELECT primary_segment, COUNT(*) AS total_customers,
                   ROUND(AVG(total_balance), 2) AS avg_balance,
                   ROUND(AVG(churn_risk_score), 1) AS avg_churn_risk,
                   ROUND(AVG(engagement_score), 1) AS avg_engagement
            FROM customer_360.gold.customer_segments
            GROUP BY primary_segment
        """)

    seg_colors = {
        "Affluent": BLUE, "Mass Market": ORANGE,
        "Digital Champion": GREEN, "At-Risk": RED
    }

    # ── 4 KPI cards ──────────────────────────────────────────────
    cols = st.columns(4)
    for i, seg in enumerate(["Affluent", "Mass Market", "Digital Champion", "At-Risk"]):
        row = seg_overview[seg_overview["primary_segment"] == seg]
        val = int(row["total_customers"].values[0]) if not row.empty else 0
        cols[i].metric(f"{seg}", f"{val:,}")

    st.divider()

    # ── Row 1: Distribution | Avg Balance ────────────────────────
    col_l, col_r = st.columns(2)
    with col_l:
        fig = px.bar(seg_overview, x="primary_segment", y="total_customers",
                    color="primary_segment", title="Customer Segment Distribution",
                    color_discrete_map=seg_colors)
        fig.update_layout(template="plotly_dark", plot_bgcolor="#1A1D24",
                          paper_bgcolor="#1A1D24", height=350, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        fig = px.bar(seg_overview, x="primary_segment", y="avg_balance",
                    color="primary_segment", title="Average Balance by Segment",
                    color_discrete_map=seg_colors)
        fig.update_layout(template="plotly_dark", plot_bgcolor="#1A1D24",
                          paper_bgcolor="#1A1D24", height=350, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # ── Row 2: Churn Risk | Engagement ────────────────────────────
    col_l2, col_r2 = st.columns(2)
    with col_l2:
        fig = px.bar(seg_overview, x="primary_segment", y="avg_churn_risk",
                    color="primary_segment", title="Churn Risk by Segment",
                    color_discrete_map=seg_colors)
        fig.update_layout(template="plotly_dark", plot_bgcolor="#1A1D24",
                          paper_bgcolor="#1A1D24", height=300, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col_r2:
        fig = px.bar(seg_overview, x="primary_segment", y="avg_engagement",
                    color="primary_segment", title="Engagement Score by Segment",
                    color_discrete_map=seg_colors)
        fig.update_layout(template="plotly_dark", plot_bgcolor="#1A1D24",
                          paper_bgcolor="#1A1D24", height=300, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Customer list with segment filter ─────────────────────────
    st.subheader("Customer List by Segment")
    segment_filter = st.selectbox(
        "Segment",
        options=["All"] + sorted(seg_overview["primary_segment"].tolist())
    )

    where_clause = "" if segment_filter == "All" else f"WHERE primary_segment = '{segment_filter}'"
    cust_list = run_query(f"""
        SELECT customer_id, full_name, city, primary_segment,
               credit_score, credit_category, total_balance,
               total_loan_amount, avg_monthly_spending, total_products,
               engagement_score, churn_risk_score
        FROM customer_360.gold.customer_segments
        {where_clause}
        ORDER BY total_balance DESC
        LIMIT 200
    """)
    st.dataframe(cust_list, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(cust_list)} of {segment_filter if segment_filter != 'All' else 'all'} customers (max 200 rows)")

# ════════════════════════════════════════════════════════════════
# PAGE 4 — PRODUCT RECOMMENDATIONS (Action Board)
# ════════════════════════════════════════════════════════════════
elif page == "🎯 Product Recommendations":
    st.title("Customer 360 Profile")
    st.caption("Page 4 of 4 · Product_Recommendations")

    customers = get_customer_list()
    selected = st.selectbox(
        "🔍 Search Customer ID",
        options=customers["customer_id"].tolist(),
        format_func=lambda x: f"{x} — {customers.loc[customers['customer_id']==x, 'full_name'].values[0]}",
        key="page4_customer"
    )

    if selected:
        with st.spinner("Generating recommendation..."):
            rec_df = run_query(f"""
                SELECT
                    customer_id, full_name, city,
                    credit_score, credit_category,
                    total_balance, total_loan_amount, avg_monthly_spending,
                    total_products, mobile_pct, total_sessions,
                    missed_payment_pct, engagement_score, churn_risk_score,
                    customer_value_tier, primary_segment,
                    has_active_credit_card, avg_payment_completion_pct,
                    mortgage_probability, mortgage_priority,
                    wealth_probability, wealth_priority,
                    credit_card_upgrade_probability, credit_card_priority,
                    top_recommendation
                FROM customer_360.gold.product_recommendations
                WHERE customer_id = '{selected}'
            """)

        if rec_df.empty:
            st.warning("No recommendation data found for this customer.")
        else:
            rec = rec_df.iloc[0]

            # ── Build risk warning in Python (no SQL string escaping issues) ──
            churn = float(rec["churn_risk_score"])
            if churn >= 60:
                risk_warning = "🚨 HIGH CHURN RISK — Prioritise retention over cross-sell"
            elif churn >= 30:
                risk_warning = "⚠️ MEDIUM CHURN RISK — Lead with value, not product push"
            else:
                risk_warning = "✅ LOW CHURN RISK — Good time to introduce new product"

            # ── Build banker script in Python ──────────────────────────────
            top_rec = rec["top_recommendation"]
            full_name = rec["full_name"]

            if top_rec == "Mortgage":
                pitch = (f'"{full_name}, based on your strong credit profile, '
                         f'you are pre-qualified for our home loan program. '
                         f'Would you like to explore our current mortgage rates?"')
            elif top_rec == "Wealth Product":
                pitch = (f'"{full_name}, given your financial strength, our wealth '
                         f'management team would love to show you investment options. '
                         f'Can we schedule a private consultation?"')
            else:
                pitch = (f'"{full_name}, you qualify for a credit card upgrade with '
                         f'higher limits and premium rewards. Would you like to hear more?"')

            if rec["mortgage_priority"] == "High":
                action = "1. Call within 48 hours — high mortgage conversion probability"
            elif rec["wealth_priority"] == "High":
                action = "1. Schedule private wealth consultation this week"
            elif rec["credit_card_priority"] == "High":
                action = "1. Send upgrade offer via preferred channel"
            else:
                action = "1. Maintain relationship — quarterly check-in"

            banker_action_script = (
                f"🎯 TOP RECOMMENDATION: {top_rec}\n\n"
                f"📞 WHAT TO SAY TO {full_name.upper()}:\n{pitch}\n\n"
                f"💼 WHY THIS RECOMMENDATION:\n"
                f"• Mortgage Score     : {rec['mortgage_probability']}/100 ({rec['mortgage_priority']})\n"
                f"• Wealth Score       : {rec['wealth_probability']}/100 ({rec['wealth_priority']})\n"
                f"• Card Upgrade Score : {rec['credit_card_upgrade_probability']}/100 ({rec['credit_card_priority']})\n\n"
                f"⚡ BANKER ACTION:\n{action}"
            )

            col_l, col_r = st.columns(2)

            with col_l:
                probs = pd.DataFrame({
                    "product": ["Mortgage", "Wealth Product", "Credit Card Upgrade"],
                    "probability": [
                        rec["mortgage_probability"],
                        rec["wealth_probability"],
                        rec["credit_card_upgrade_probability"]
                    ],
                    "priority": [
                        rec["mortgage_priority"],
                        rec["wealth_priority"],
                        rec["credit_card_priority"]
                    ]
                })
                priority_colors = {"High": RED, "Medium": ORANGE, "Low": GREEN}
                fig = px.bar(probs, x="probability", y="product", orientation="h",
                            color="priority", color_discrete_map=priority_colors,
                            title="Product Probability for Selected Customer")
                fig.update_layout(template="plotly_dark", plot_bgcolor="#1A1D24",
                                  paper_bgcolor="#1A1D24", height=300)
                st.plotly_chart(fig, use_container_width=True)

            with col_r:
                st.subheader("Banker Recommendation Script")
                st.markdown(
                    f"""<div style="background-color:#1A1D24; padding:18px;
                    border-radius:10px; border:1px solid #2D3139; white-space:pre-wrap;
                    font-size:13px; line-height:1.6; height:280px; overflow-y:auto;">
                    {banker_action_script}
                    </div>""",
                    unsafe_allow_html=True
                )
                st.warning(risk_warning)

        st.divider()

        # ── Portfolio-level view ─────────────────────────────────
        st.subheader("Portfolio Overview")

        top_recs = run_query("""
            SELECT top_recommendation, COUNT(*) AS customers
            FROM customer_360.gold.product_recommendations
            GROUP BY top_recommendation
        """)

        c1, c2, c3 = st.columns(3)
        for col, prod in zip([c1, c2, c3], ["Mortgage", "Wealth Product", "Credit Card Upgrade"]):
            row = top_recs[top_recs["top_recommendation"] == prod]
            val = int(row["customers"].values[0]) if not row.empty else 0
            col.metric(f"{prod} Candidates", f"{val:,}")

        col_l2, col_r2 = st.columns(2)
        with col_l2:
            fig = px.bar(top_recs, x="top_recommendation", y="customers",
                        color="top_recommendation", title="Top Recommendation Distribution",
                        color_discrete_sequence=[BLUE, GREEN, ORANGE])
            fig.update_layout(template="plotly_dark", plot_bgcolor="#1A1D24",
                              paper_bgcolor="#1A1D24", height=350, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        with col_r2:
            avg_probs = run_query("""
                SELECT 'Mortgage' AS product, mortgage_priority AS priority,
                       AVG(mortgage_probability) AS avg_prob
                FROM customer_360.gold.product_recommendations
                GROUP BY mortgage_priority
                UNION ALL
                SELECT 'Wealth' AS product, wealth_priority AS priority,
                       AVG(wealth_probability) AS avg_prob
                FROM customer_360.gold.product_recommendations
                GROUP BY wealth_priority
                UNION ALL
                SELECT 'Card Upgrade' AS product, credit_card_priority AS priority,
                       AVG(credit_card_upgrade_probability) AS avg_prob
                FROM customer_360.gold.product_recommendations
                GROUP BY credit_card_priority
            """)
            priority_colors = {"High": RED, "Medium": ORANGE, "Low": GREEN}
            fig = px.bar(avg_probs, x="product", y="avg_prob", color="priority",
                        barmode="group", title="Avg Probability by Product",
                        color_discrete_map=priority_colors)
            fig.update_layout(template="plotly_dark", plot_bgcolor="#1A1D24",
                              paper_bgcolor="#1A1D24", height=350)
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Customer Product Probability List")
        full_list = run_query("""
            SELECT customer_id, full_name, city,
                   mortgage_probability, mortgage_priority,
                   wealth_probability, wealth_priority,
                   credit_card_upgrade_probability, credit_card_priority,
                   top_recommendation, engagement_score
            FROM customer_360.gold.product_recommendations
            ORDER BY mortgage_probability DESC
            LIMIT 200
        """)
        st.dataframe(full_list, use_container_width=True, hide_index=True)
