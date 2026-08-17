# -*- coding: utf-8 -*-

import os
from datetime import timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
import streamlit as st
from plotly.subplots import make_subplots


# =============================================================================
# CONFIGURAÇÃO VISUAL
# =============================================================================

st.set_page_config(
    page_title="LH Nautical | Dashboard Executivo",
    page_icon="🚤",
    layout="wide",
    initial_sidebar_state="collapsed",
)

NAVY = "#1a3a5c"
GOLD = "#e89c31"
RED = "#d9534f"
GREEN = "#2e8b57"
LIGHT_BG = "#f5f5f5"
WHITE = "#ffffff"
MUTED = "#667085"

st.markdown(
    f"""
    <style>
        .stApp {{ background-color: {LIGHT_BG}; }}
        .block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1800px; }}
        h1, h2, h3 {{ color: {NAVY}; font-family: 'Segoe UI', Arial, sans-serif; }}
        .dashboard-subtitle {{ color: {MUTED}; font-size: .95rem; margin-top: -.6rem; margin-bottom: 1rem; }}
        .section-title {{ color: {NAVY}; font-size: 1.20rem; font-weight: 700; margin: .7rem 0 .45rem 0; }}
        .kpi-card {{ background: {WHITE}; border-radius: 14px; padding: 18px 20px; min-height: 120px;
                     border: 1px solid #e7e9ee; box-shadow: 0 4px 12px rgba(26,58,92,.06); }}
        .kpi-label {{ color: {MUTED}; font-size: .82rem; font-weight: 600; text-transform: uppercase; letter-spacing: .04rem; }}
        .kpi-value {{ color: {NAVY}; font-size: 2rem; line-height: 2.35rem; font-weight: 800; margin-top: .45rem; }}
        .kpi-delta-positive {{ color: {GREEN}; font-size: .82rem; font-weight: 600; margin-top: .40rem; }}
        .kpi-delta-negative {{ color: {RED}; font-size: .82rem; font-weight: 600; margin-top: .40rem; }}
        .kpi-delta-neutral {{ color: {MUTED}; font-size: .82rem; font-weight: 600; margin-top: .40rem; }}
        .empty-card {{ background: {WHITE}; border: 1px dashed #c8cdd6; border-radius: 14px; padding: 28px;
                       color: {MUTED}; min-height: 280px; display: flex; align-items: center; justify-content: center;
                       text-align: center; }}
        footer {{ visibility: hidden; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# CONEXÃO POSTGRESQL
# =============================================================================

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "erp_analytics")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres123")


@st.cache_resource
def obter_conexao():
    """Abre uma conexão reutilizável com o PostgreSQL."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def consultar_df(sql, params=None):
    """Executa SQL parametrizado e devolve o resultado como DataFrame."""
    conn = obter_conexao()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        conn.rollback()
        raise


# =============================================================================
# FORMATAÇÃO
# =============================================================================

def brl(valor):
    """Formata um número como moeda brasileira."""
    if valor is None or pd.isna(valor):
        return "R$ 0,00"
    texto = f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def inteiro(valor):
    """Formata um inteiro com separador de milhar brasileiro."""
    if valor is None or pd.isna(valor):
        return "0"
    return f"{int(round(float(valor))):,}".replace(",", ".")


def pct(valor):
    """Formata percentual com uma casa decimal."""
    if valor is None or pd.isna(valor):
        return "—"
    return f"{float(valor):.1f}%".replace(".", ",")


def variacao(atual, anterior):
    """Calcula a variação percentual do período atual contra o anterior."""
    if anterior is None or pd.isna(anterior) or float(anterior) == 0:
        return None
    return ((float(atual) - float(anterior)) / abs(float(anterior))) * 100.0


def card_kpi(icone, titulo, valor, delta):
    """Renderiza um card KPI com variação contra o período anterior."""
    if delta is None:
        delta_html = '<div class="kpi-delta-neutral">Sem base comparável</div>'
    elif delta > 0:
        delta_html = f'<div class="kpi-delta-positive">▲ {pct(delta)} vs. período anterior</div>'
    elif delta < 0:
        delta_html = f'<div class="kpi-delta-negative">▼ {pct(abs(delta))} vs. período anterior</div>'
    else:
        delta_html = '<div class="kpi-delta-neutral">• 0,0% vs. período anterior</div>'

    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{icone} {titulo}</div>
            <div class="kpi-value">{valor}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def vazio(mensagem="Nenhum dado disponível para o período selecionado."):
    """Mostra um estado vazio padronizado."""
    st.markdown(f'<div class="empty-card">📭 {mensagem}</div>', unsafe_allow_html=True)


def estilo_figura(fig, altura=390):
    """Aplica identidade visual comum aos gráficos Plotly."""
    fig.update_layout(
        height=altura,
        margin=dict(l=10, r=10, t=25, b=10),
        paper_bgcolor=WHITE,
        plot_bgcolor=WHITE,
        font=dict(family="Segoe UI, Arial", color=NAVY),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hoverlabel=dict(bgcolor=WHITE, font_size=13),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#edf0f4", zeroline=False)
    return fig


# =============================================================================
# METADADOS E RENTABILIDADE
# =============================================================================

@st.cache_data(ttl=300)
def obter_schema():
    """Lê as colunas reais do schema public para evitar assumir campos inexistentes."""
    return consultar_df(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public';
        """
    )


def mapa_schema():
    """Transforma os metadados em {tabela: {colunas}}."""
    df = obter_schema()
    return {tabela: set(g["column_name"].tolist()) for tabela, g in df.groupby("table_name")}


def detectar_rentabilidade():
    """
    Detecta uma fórmula de lucro somente quando os campos necessários realmente existem.
    Se não houver custo/profit validável, retorna None e o dashboard não inventa rentabilidade.
    """
    schema = mapa_schema()
    oi = schema.get("order_items", set())
    pv = schema.get("product_variants", set())

    if "profit" in oi:
        return {"descricao": "order_items.profit", "profit": "oi.profit", "receita": None, "custo": None}
    if {"line_total", "cost_total"}.issubset(oi):
        return {
            "descricao": "order_items.line_total - order_items.cost_total",
            "profit": "(oi.line_total - oi.cost_total)",
            "receita": "oi.line_total",
            "custo": "oi.cost_total",
        }
    if {"total", "cost_total"}.issubset(oi):
        return {
            "descricao": "order_items.total - order_items.cost_total",
            "profit": "(oi.total - oi.cost_total)",
            "receita": "oi.total",
            "custo": "oi.cost_total",
        }
    if {"unit_price", "unit_cost", "quantity"}.issubset(oi):
        return {
            "descricao": "(unit_price - unit_cost) × quantity",
            "profit": "((oi.unit_price - oi.unit_cost) * oi.quantity)",
            "receita": "(oi.unit_price * oi.quantity)",
            "custo": "(oi.unit_cost * oi.quantity)",
        }
    if {"price", "cost", "quantity"}.issubset(oi):
        return {
            "descricao": "(price - cost) × quantity",
            "profit": "((oi.price - oi.cost) * oi.quantity)",
            "receita": "(oi.price * oi.quantity)",
            "custo": "(oi.cost * oi.quantity)",
        }
    if {"unit_price", "quantity"}.issubset(oi) and "cost_price" in pv:
        return {
            "descricao": "(order_items.unit_price - product_variants.cost_price) × quantity",
            "profit": "((oi.unit_price - pv.cost_price) * oi.quantity)",
            "receita": "(oi.unit_price * oi.quantity)",
            "custo": "(pv.cost_price * oi.quantity)",
        }
    if {"price", "quantity"}.issubset(oi) and "cost" in pv:
        return {
            "descricao": "(order_items.price - product_variants.cost) × quantity",
            "profit": "((oi.price - pv.cost) * oi.quantity)",
            "receita": "(oi.price * oi.quantity)",
            "custo": "(pv.cost * oi.quantity)",
        }
    return None


# =============================================================================
# FILTROS SQL
# =============================================================================

def filtro_canal_sql(canais):
    """Cria filtro de canal usando placeholders, sem concatenar valores do usuário no SQL."""
    if not canais:
        return "", []
    placeholders = ", ".join(["%s"] * len(canais))
    return f" AND o.channel IN ({placeholders}) ", list(canais)


def filtro_periodo(data_inicio, data_fim, canais):
    """Usa limite superior exclusivo para incluir todas as horas do último dia."""
    trecho, params_canais = filtro_canal_sql(canais)
    return trecho, [data_inicio, data_fim + timedelta(days=1)] + params_canais


# =============================================================================
# QUERIES PRINCIPAIS
# =============================================================================

@st.cache_data(ttl=60, show_spinner=False)
def buscar_kpis(data_inicio, data_fim, canais):
    canal_sql, params = filtro_periodo(data_inicio, data_fim, canais)
    sql = f"""
        SELECT
            COALESCE(SUM(o.total), 0) AS faturamento_total,
            COUNT(DISTINCT o.id) AS numero_pedidos,
            COALESCE(SUM(o.total) / NULLIF(COUNT(DISTINCT o.id), 0), 0) AS ticket_medio
        FROM orders AS o
        WHERE o.placed_at >= %s
          AND o.placed_at < %s
          {canal_sql};
    """
    return consultar_df(sql, params).iloc[0]


@st.cache_data(ttl=60, show_spinner=False)
def buscar_evolucao(data_inicio, data_fim, canais):
    canal_sql, params = filtro_periodo(data_inicio, data_fim, canais)
    sql = f"""
        SELECT
            DATE_TRUNC('month', o.placed_at)::date AS mes,
            SUM(o.total) AS faturamento,
            COUNT(DISTINCT o.id) AS pedidos
        FROM orders AS o
        WHERE o.placed_at >= %s
          AND o.placed_at < %s
          {canal_sql}
        GROUP BY DATE_TRUNC('month', o.placed_at)
        ORDER BY mes;
    """
    return consultar_df(sql, params)


def cte_clientes_fieis(canal_sql):
    """CTEs reutilizadas pelos indicadores de clientes fiéis e categorias."""
    return f"""
        WITH pedidos_filtrados AS (
            SELECT o.id, o.customer_id, o.total
            FROM orders AS o
            WHERE o.placed_at >= %s
              AND o.placed_at < %s
              {canal_sql}
              AND o.customer_id IS NOT NULL
        ),
        metricas_financeiras AS (
            SELECT
                pf.customer_id,
                SUM(pf.total) AS faturamento_total,
                COUNT(DISTINCT pf.id) AS frequencia,
                SUM(pf.total) / NULLIF(COUNT(DISTINCT pf.id), 0) AS ticket_medio
            FROM pedidos_filtrados AS pf
            GROUP BY pf.customer_id
        ),
        diversidade AS (
            SELECT
                pf.customer_id,
                COUNT(DISTINCT p.category_id) AS diversidade_categorias
            FROM pedidos_filtrados AS pf
            INNER JOIN order_items AS oi ON oi.order_id = pf.id
            INNER JOIN product_variants AS pv ON pv.id = oi.product_variant_id
            INNER JOIN products AS p ON p.id = pv.product_id
            WHERE p.category_id IS NOT NULL
            GROUP BY pf.customer_id
        ),
        top_10 AS (
            SELECT
                mf.customer_id,
                mf.faturamento_total,
                mf.frequencia,
                mf.ticket_medio,
                d.diversidade_categorias
            FROM metricas_financeiras AS mf
            INNER JOIN diversidade AS d ON d.customer_id = mf.customer_id
            WHERE d.diversidade_categorias >= 13
            ORDER BY mf.ticket_medio DESC, mf.customer_id ASC
            LIMIT 10
        )
    """


@st.cache_data(ttl=60, show_spinner=False)
def buscar_clientes_fieis(data_inicio, data_fim, canais):
    canal_sql, params = filtro_periodo(data_inicio, data_fim, canais)
    sql = cte_clientes_fieis(canal_sql) + """
        SELECT customer_id, faturamento_total, frequencia, ticket_medio, diversidade_categorias
        FROM top_10
        ORDER BY ticket_medio DESC, customer_id ASC;
    """
    return consultar_df(sql, params)


@st.cache_data(ttl=60, show_spinner=False)
def buscar_categorias_elite(data_inicio, data_fim, canais):
    canal_sql, params = filtro_periodo(data_inicio, data_fim, canais)
    schema = mapa_schema()
    tem_nome_categoria = "categories" in schema and "name" in schema["categories"]

    if tem_nome_categoria:
        categoria_expr = "COALESCE(c.name, 'Categoria ' || p.category_id::text)"
        join_categoria = "LEFT JOIN categories AS c ON c.id = p.category_id"
    else:
        categoria_expr = "'Categoria ' || p.category_id::text"
        join_categoria = ""

    sql = cte_clientes_fieis(canal_sql) + f"""
        , consumo AS (
            SELECT
                p.category_id,
                {categoria_expr} AS categoria,
                SUM(oi.quantity) AS quantidade_itens
            FROM top_10 AS t
            INNER JOIN orders AS o ON o.customer_id = t.customer_id
            INNER JOIN order_items AS oi ON oi.order_id = o.id
            INNER JOIN product_variants AS pv ON pv.id = oi.product_variant_id
            INNER JOIN products AS p ON p.id = pv.product_id
            {join_categoria}
            WHERE o.placed_at >= %s
              AND o.placed_at < %s
              {canal_sql}
              AND p.category_id IS NOT NULL
            GROUP BY p.category_id, {categoria_expr}
        ),
        total_grupo AS (
            SELECT SUM(quantidade_itens) AS total_itens FROM consumo
        )
        SELECT
            c.category_id,
            c.categoria,
            c.quantidade_itens,
            CASE WHEN tg.total_itens > 0
                 THEN (c.quantidade_itens::numeric / tg.total_itens) * 100.0
                 ELSE 0 END AS percentual_grupo
        FROM consumo AS c
        CROSS JOIN total_grupo AS tg
        ORDER BY c.quantidade_itens DESC, c.category_id ASC
        LIMIT 10;
    """
    return consultar_df(sql, params + params)


@st.cache_data(ttl=60, show_spinner=False)
def buscar_pos(data_inicio, data_fim, canais):
    """Calcula os indicadores 9 e 10 preservando todos os dias do calendário."""
    if canais and "pos" not in canais:
        return pd.DataFrame()

    sql = """
        WITH calendario AS (
            SELECT
                gs::date AS data_calendario,
                EXTRACT(ISODOW FROM gs)::integer AS numero_dia_semana,
                CASE EXTRACT(ISODOW FROM gs)::integer
                    WHEN 1 THEN 'Segunda-feira'
                    WHEN 2 THEN 'Terça-feira'
                    WHEN 3 THEN 'Quarta-feira'
                    WHEN 4 THEN 'Quinta-feira'
                    WHEN 5 THEN 'Sexta-feira'
                    WHEN 6 THEN 'Sábado'
                    WHEN 7 THEN 'Domingo'
                END AS dia_semana
            FROM generate_series(%s::date, %s::date, INTERVAL '1 day') AS gs
        ),
        vendas_pos AS (
            SELECT
                o.placed_at::date AS data_venda,
                SUM(o.total) AS valor_venda_diaria
            FROM orders AS o
            WHERE o.placed_at >= %s
              AND o.placed_at < %s
              AND o.channel = 'pos'
            GROUP BY o.placed_at::date
        ),
        base AS (
            SELECT
                c.data_calendario,
                c.numero_dia_semana,
                c.dia_semana,
                COALESCE(v.valor_venda_diaria, 0::numeric) AS valor_venda_diaria
            FROM calendario AS c
            LEFT JOIN vendas_pos AS v ON v.data_venda = c.data_calendario
        )
        SELECT
            numero_dia_semana,
            dia_semana,
            COUNT(*) AS dias_calendario,
            COUNT(*) FILTER (WHERE valor_venda_diaria > 0) AS dias_com_venda,
            COUNT(*) FILTER (WHERE valor_venda_diaria = 0) AS dias_sem_venda,
            AVG(valor_venda_diaria) AS media_vendas,
            CASE WHEN COUNT(*) > 0
                 THEN COUNT(*) FILTER (WHERE valor_venda_diaria = 0)::numeric / COUNT(*)::numeric * 100.0
                 ELSE 0 END AS taxa_dias_sem_venda
        FROM base
        GROUP BY numero_dia_semana, dia_semana
        ORDER BY numero_dia_semana;
    """
    params = [data_inicio, data_fim, data_inicio, data_fim + timedelta(days=1)]
    return consultar_df(sql, params)


@st.cache_data(ttl=60, show_spinner=False)
def buscar_prejuizos(data_inicio, data_fim, canais, descricao_modelo):
    modelo = detectar_rentabilidade()
    if modelo is None or modelo["descricao"] != descricao_modelo:
        return pd.DataFrame()

    canal_sql, params = filtro_periodo(data_inicio, data_fim, canais)
    profit = modelo["profit"]
    receita = modelo["receita"]
    custo = modelo["custo"]

    receita_sql = f"SUM({receita})" if receita else "NULL::numeric"
    custo_sql = f"SUM({custo})" if custo else "NULL::numeric"
    margem_sql = (
        f"CASE WHEN {receita_sql} <> 0 THEN (SUM({profit}) / {receita_sql}) * 100.0 ELSE NULL END"
        if receita else "NULL::numeric"
    )

    sql = f"""
        SELECT
            p.id AS product_id,
            p.name AS produto,
            SUM({profit}) AS lucro_total,
            SUM(oi.quantity) AS quantidade_vendida,
            {receita_sql} AS receita_produto,
            {custo_sql} AS custo_produto,
            {margem_sql} AS margem_percentual
        FROM orders AS o
        INNER JOIN order_items AS oi ON oi.order_id = o.id
        INNER JOIN product_variants AS pv ON pv.id = oi.product_variant_id
        INNER JOIN products AS p ON p.id = pv.product_id
        WHERE o.placed_at >= %s
          AND o.placed_at < %s
          {canal_sql}
        GROUP BY p.id, p.name
        HAVING SUM({profit}) < 0
        ORDER BY lucro_total ASC
        LIMIT 15;
    """
    return consultar_df(sql, params)


@st.cache_data(ttl=60, show_spinner=False)
def buscar_lucro_clientes(data_inicio, data_fim, canais, descricao_modelo):
    modelo = detectar_rentabilidade()
    if modelo is None or modelo["descricao"] != descricao_modelo:
        return pd.DataFrame()

    canal_sql, params = filtro_periodo(data_inicio, data_fim, canais)
    profit = modelo["profit"]

    sql = f"""
        WITH lucro_por_cliente AS (
            SELECT
                o.customer_id,
                SUM({profit}) AS lucro_acumulado
            FROM orders AS o
            INNER JOIN order_items AS oi ON oi.order_id = o.id
            INNER JOIN product_variants AS pv ON pv.id = oi.product_variant_id
            WHERE o.placed_at >= %s
              AND o.placed_at < %s
              {canal_sql}
              AND o.customer_id IS NOT NULL
            GROUP BY o.customer_id
        ),
        metricas_orders AS (
            SELECT
                o.customer_id,
                SUM(o.total) AS faturamento_total,
                COUNT(DISTINCT o.id) AS numero_pedidos,
                SUM(o.total) / NULLIF(COUNT(DISTINCT o.id), 0) AS ticket_medio
            FROM orders AS o
            WHERE o.placed_at >= %s
              AND o.placed_at < %s
              {canal_sql}
              AND o.customer_id IS NOT NULL
            GROUP BY o.customer_id
        )
        SELECT
            l.customer_id,
            l.lucro_acumulado,
            m.faturamento_total,
            m.numero_pedidos,
            m.ticket_medio
        FROM lucro_por_cliente AS l
        INNER JOIN metricas_orders AS m ON m.customer_id = l.customer_id
        WHERE l.lucro_acumulado > 0
        ORDER BY l.lucro_acumulado DESC
        LIMIT 30;
    """
    return consultar_df(sql, params + params)


# =============================================================================
# HEADER E FILTROS
# =============================================================================

st.title("🚤 LH Nautical — Dashboard Executivo de Operações Comerciais")
st.markdown(
    '<div class="dashboard-subtitle">Performance financeira • Clientes • Rentabilidade • Operação física • Lealdade</div>',
    unsafe_allow_html=True,
)

try:
    datas = consultar_df(
        """
        SELECT MIN(placed_at)::date AS data_minima, MAX(placed_at)::date AS data_maxima
        FROM orders
        WHERE placed_at IS NOT NULL;
        """
    ).iloc[0]
except Exception as erro:
    st.error("Não foi possível conectar ao PostgreSQL.")
    st.code(str(erro))
    st.info("Configure DB_HOST, DB_PORT, DB_NAME, DB_USER e DB_PASSWORD antes de iniciar o dashboard.")
    st.stop()

if pd.isna(datas["data_minima"]) or pd.isna(datas["data_maxima"]):
    st.warning("A tabela orders não possui datas válidas em placed_at.")
    st.stop()

min_date = pd.to_datetime(datas["data_minima"]).date()
max_date = pd.to_datetime(datas["data_maxima"]).date()

canais_disponiveis = consultar_df(
    "SELECT DISTINCT channel FROM orders WHERE channel IS NOT NULL ORDER BY channel;"
)["channel"].tolist()

f1, f2, f3 = st.columns([2.2, 1.8, 1.2])
with f1:
    periodo = st.date_input(
        "📅 Período",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        format="DD/MM/YYYY",
    )
with f2:
    canais = st.multiselect(
        "🛒 Canal de Venda",
        options=canais_disponiveis,
        default=canais_disponiveis,
        help="Desmarque canais para restringir os indicadores gerais.",
    )
with f3:
    st.markdown("<br>", unsafe_allow_html=True)
    st.caption(f"Base disponível: {min_date:%d/%m/%Y} → {max_date:%d/%m/%Y}")

if not isinstance(periodo, (tuple, list)) or len(periodo) != 2:
    st.info("Selecione a data inicial e a data final.")
    st.stop()

data_inicio, data_fim = periodo
if data_inicio > data_fim:
    st.error("A data inicial não pode ser posterior à data final.")
    st.stop()


# =============================================================================
# KPIs + COMPARAÇÃO COM PERÍODO ANTERIOR
# =============================================================================

dias_periodo = (data_fim - data_inicio).days + 1
fim_anterior = data_inicio - timedelta(days=1)
inicio_anterior = fim_anterior - timedelta(days=dias_periodo - 1)

kpis = buscar_kpis(data_inicio, data_fim, tuple(canais))
kpis_prev = buscar_kpis(inicio_anterior, fim_anterior, tuple(canais))

st.markdown('<div class="section-title">Visão Geral</div>', unsafe_allow_html=True)
k1, k2, k3 = st.columns(3)
with k1:
    card_kpi("💰", "Faturamento Total", brl(kpis["faturamento_total"]), variacao(kpis["faturamento_total"], kpis_prev["faturamento_total"]))
with k2:
    card_kpi("🧾", "Número de Pedidos", inteiro(kpis["numero_pedidos"]), variacao(kpis["numero_pedidos"], kpis_prev["numero_pedidos"]))
with k3:
    card_kpi("🎟️", "Ticket Médio", brl(kpis["ticket_medio"]), variacao(kpis["ticket_medio"], kpis_prev["ticket_medio"]))


# =============================================================================
# EVOLUÇÃO MENSAL
# =============================================================================

st.markdown('<div class="section-title">Evolução Mensal</div>', unsafe_allow_html=True)
evolucao = buscar_evolucao(data_inicio, data_fim, tuple(canais))

if evolucao.empty:
    vazio()
else:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=evolucao["mes"],
            y=evolucao["faturamento"],
            mode="lines+markers",
            name="Faturamento",
            line=dict(color=NAVY, width=3),
            marker=dict(size=7),
            customdata=evolucao[["pedidos"]],
            hovertemplate="<b>%{x|%m/%Y}</b><br>Faturamento: R$ %{y:,.2f}<br>Pedidos: %{customdata[0]:,.0f}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=evolucao["mes"],
            y=evolucao["pedidos"],
            mode="lines+markers",
            name="Pedidos",
            line=dict(color=GOLD, width=3, dash="dot"),
            marker=dict(size=7),
            hovertemplate="<b>%{x|%m/%Y}</b><br>Pedidos: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=True,
    )
    estilo_figura(fig, 420)
    fig.update_yaxes(title_text="Faturamento (R$)", secondary_y=False)
    fig.update_yaxes(title_text="Pedidos", secondary_y=True)
    fig.update_xaxes(title_text="Mês/Ano")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# =============================================================================
# RENTABILIDADE
# =============================================================================

st.markdown('<div class="section-title">Rentabilidade</div>', unsafe_allow_html=True)
modelo = detectar_rentabilidade()
r1, r2 = st.columns(2)

with r1:
    st.markdown("#### 📉 Ranking de Prejuízos por Produto")
    if modelo is None:
        vazio("Indicador indisponível: a base atual não possui custo/profit validado. Nenhum prejuízo foi estimado artificialmente.")
    else:
        df = buscar_prejuizos(data_inicio, data_fim, tuple(canais), modelo["descricao"])
        if df.empty:
            vazio("Nenhum produto com resultado negativo no período selecionado.")
        else:
            plot = df.sort_values("lucro_total", ascending=False)
            fig = px.bar(plot, x="lucro_total", y="produto", orientation="h", custom_data=["quantidade_vendida", "margem_percentual"])
            fig.update_traces(
                marker_color=RED,
                hovertemplate="<b>%{y}</b><br>Prejuízo: R$ %{x:,.2f}<br>Qtd. vendida: %{customdata[0]:,.0f}<br>Margem: %{customdata[1]:.1f}%<extra></extra>",
            )
            estilo_figura(fig)
            fig.update_xaxes(title="Resultado (R$)")
            fig.update_yaxes(title="")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

with r2:
    # -------------------------------------------------------------------------
    # MATRIZ DE VALOR & RENTABILIDADE DO CLIENTE
    # -------------------------------------------------------------------------
    # Uma barra mostrava apenas "quem tem mais lucro".
    # A matriz abaixo cruza quatro dimensões simultaneamente:
    #
    # eixo X  -> faturamento total;
    # eixo Y  -> lucro acumulado;
    # bolha   -> quantidade de pedidos;
    # cor     -> ticket médio.
    #
    # As linhas de mediana criam quadrantes e ajudam a identificar rapidamente
    # clientes de alto valor e alta rentabilidade.
    # -------------------------------------------------------------------------

    st.markdown("#### 💎 Matriz de Valor & Rentabilidade dos Clientes")

    if modelo is None:
        # Sem custo/profit validável não há base técnica para calcular lucro.
        vazio(
            "Indicador indisponível: lucro por cliente exige custo/profit "
            "verificável no grão do item."
        )

    else:
        # Recupera os clientes de maior lucro do período filtrado.
        df = buscar_lucro_clientes(
            data_inicio,
            data_fim,
            tuple(canais),
            modelo["descricao"],
        )

        if df.empty:
            # Estado vazio para períodos sem clientes com lucro positivo.
            vazio("Nenhum cliente com lucro positivo no período selecionado.")

        else:
            # Cria um rótulo textual para identificar cada cliente no tooltip.
            df["cliente"] = df["customer_id"].astype(str)

            # Calcula medianas para separar visualmente os quatro quadrantes.
            mediana_faturamento = float(df["faturamento_total"].median())
            mediana_lucro = float(df["lucro_acumulado"].median())

            # Garante que o tamanho das bolhas permaneça positivo e legível.
            tamanhos = df["numero_pedidos"].clip(lower=1)

            # Constrói a matriz de dispersão.
            fig = go.Figure()

            fig.add_trace(
                go.Scatter(
                    # Eixo horizontal: dimensão de valor comercial.
                    x=df["faturamento_total"],

                    # Eixo vertical: dimensão de rentabilidade.
                    y=df["lucro_acumulado"],

                    # Cada cliente é representado por uma bolha.
                    mode="markers",

                    # Nome da série apresentado na legenda/tooltip.
                    name="Clientes",

                    marker=dict(
                        # O tamanho representa quantidade de pedidos.
                        size=tamanhos,

                        # Ajusta automaticamente a escala das bolhas.
                        sizemode="area",

                        # Mantém a maior bolha em tamanho visual controlado.
                        sizeref=max(2.0 * float(tamanhos.max()) / (38.0 ** 2), 0.01),

                        # Impede pontos pequenos demais.
                        sizemin=8,

                        # A cor representa Ticket Médio.
                        color=df["ticket_medio"],

                        # Usa a identidade visual do dashboard.
                        colorscale=[
                            [0.0, GOLD],
                            [1.0, NAVY],
                        ],

                        # Exibe uma barra lateral explicando a escala de cor.
                        colorbar=dict(
                            title="Ticket<br>Médio",
                            tickprefix="R$ ",
                            thickness=12,
                        ),

                        # Adiciona contorno branco para melhorar separação visual.
                        line=dict(
                            color=WHITE,
                            width=1.5,
                        ),

                        # Mantém leve transparência quando bolhas se sobrepõem.
                        opacity=0.82,
                    ),

                    # Envia dados adicionais para o tooltip.
                    customdata=df[
                        [
                            "customer_id",
                            "numero_pedidos",
                            "ticket_medio",
                        ]
                    ],

                    # Tooltip executivo com todas as métricas relevantes.
                    hovertemplate=(
                        "<b>Cliente %{customdata[0]}</b><br>"
                        "Faturamento: R$ %{x:,.2f}<br>"
                        "Lucro acumulado: R$ %{y:,.2f}<br>"
                        "Pedidos: %{customdata[1]:,.0f}<br>"
                        "Ticket médio: R$ %{customdata[2]:,.2f}"
                        "<extra></extra>"
                    ),
                )
            )

            # Linha vertical: mediana de faturamento.
            fig.add_vline(
                x=mediana_faturamento,
                line_width=1.4,
                line_dash="dash",
                line_color=MUTED,
                annotation_text="Mediana de faturamento",
                annotation_position="top left",
            )

            # Linha horizontal: mediana de lucro.
            fig.add_hline(
                y=mediana_lucro,
                line_width=1.4,
                line_dash="dash",
                line_color=MUTED,
                annotation_text="Mediana de lucro",
                annotation_position="bottom right",
            )

            # Identifica o cliente de maior lucro para chamar atenção executiva.
            destaque = df.loc[df["lucro_acumulado"].idxmax()]

            fig.add_annotation(
                x=float(destaque["faturamento_total"]),
                y=float(destaque["lucro_acumulado"]),
                text=f"🏆 Cliente {destaque['customer_id']}",
                showarrow=True,
                arrowhead=2,
                ax=35,
                ay=-35,
                bgcolor=WHITE,
                bordercolor=GOLD,
                borderwidth=1,
                font=dict(color=NAVY, size=11),
            )

            # Destaca semanticamente o quadrante mais desejável.
            fig.add_annotation(
                x=0.99,
                y=0.98,
                xref="paper",
                yref="paper",
                text="⭐ Alto faturamento<br>+ Alto lucro",
                showarrow=False,
                xanchor="right",
                yanchor="top",
                bgcolor="rgba(255,255,255,0.88)",
                bordercolor=GOLD,
                borderwidth=1,
                font=dict(color=NAVY, size=11),
            )

            # Aplica o padrão visual comum do dashboard.
            estilo_figura(fig, 430)

            # Nomeia os eixos com significado de negócio.
            fig.update_xaxes(
                title="Faturamento Total (R$)",
                tickprefix="R$ ",
            )

            fig.update_yaxes(
                title="Lucro Acumulado (R$)",
                tickprefix="R$ ",
            )

            # Remove legenda redundante: há apenas uma série.
            fig.update_layout(
                showlegend=False,
            )

            # Renderiza a matriz ocupando toda a coluna disponível.
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )

            # Explicação curta para quem lê o dashboard sem contexto técnico.
            st.caption(
                "💡 Leitura: quanto mais à direita, maior o faturamento; "
                "quanto mais acima, maior o lucro. O tamanho da bolha representa "
                "nº de pedidos e a cor representa Ticket Médio."
            )

if modelo is not None:
    st.caption(f"ℹ️ Fórmula de rentabilidade detectada automaticamente: {modelo['descricao']}.")


# =============================================================================
# CLIENTES FIÉIS E CATEGORIAS
# =============================================================================

st.markdown('<div class="section-title">Clientes Fiéis & Preferências</div>', unsafe_allow_html=True)
c1, c2 = st.columns(2)

with c1:
    # -------------------------------------------------------------------------
    # MATRIZ DE FIDELIDADE DOS TOP 10
    # -------------------------------------------------------------------------
    # O ranking por barras respondia "quem tem maior Ticket Médio", mas ocultava
    # a relação entre as quatro dimensões de fidelidade disponíveis.
    #
    # eixo X  -> diversidade de categorias;
    # eixo Y  -> Ticket Médio;
    # bolha   -> faturamento total;
    # cor     -> frequência de pedidos.
    #
    # Todos os pontos já passaram pela regra de elegibilidade:
    # diversidade_categorias >= 13.
    # -------------------------------------------------------------------------

    st.markdown("#### 🧭 Matriz de Fidelidade — Top 10 Clientes")

    # Recupera exatamente os dez clientes definidos pela regra de elite.
    fieis = buscar_clientes_fieis(
        data_inicio,
        data_fim,
        tuple(canais),
    )

    if fieis.empty:
        # Exibe estado vazio quando ninguém atinge a diversidade mínima.
        vazio(
            "Nenhum cliente atingiu o critério de 13 ou mais categorias "
            "no período selecionado."
        )

    else:
        # Cria label textual para cada cliente.
        fieis["cliente"] = fieis["customer_id"].astype(str)

        # Calcula medianas do próprio grupo elite para formar quadrantes.
        mediana_diversidade = float(fieis["diversidade_categorias"].median())
        mediana_ticket = float(fieis["ticket_medio"].median())

        # Faturamento é utilizado como tamanho da bolha.
        # clip evita valores nulos/negativos inviabilizando a escala.
        faturamento_bolha = fieis["faturamento_total"].clip(lower=1)

        # Calcula uma referência estável para o tamanho das bolhas.
        sizeref = max(
            2.0 * float(faturamento_bolha.max()) / (42.0 ** 2),
            0.01,
        )

        # Cria a matriz.
        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                # Eixo X representa amplitude do relacionamento com a empresa.
                x=fieis["diversidade_categorias"],

                # Eixo Y representa valor médio de cada transação.
                y=fieis["ticket_medio"],

                # Mostra bolhas e o customer_id diretamente no gráfico.
                mode="markers+text",

                # Escreve o identificador do cliente ao lado do ponto.
                text=fieis["cliente"],

                # Posiciona o texto acima das bolhas.
                textposition="top center",

                # Define estilo discreto para os identificadores.
                textfont=dict(
                    size=10,
                    color=NAVY,
                ),

                marker=dict(
                    # Tamanho da bolha = faturamento acumulado.
                    size=faturamento_bolha,

                    # Usa escala por área para evitar distorção perceptiva.
                    sizemode="area",

                    # Controla a maior bolha.
                    sizeref=sizeref,

                    # Mantém todos os clientes visíveis.
                    sizemin=10,

                    # Cor da bolha = frequência de compra.
                    color=fieis["frequencia"],

                    # Gradiente alinhado à identidade LH Nautical.
                    colorscale=[
                        [0.0, GOLD],
                        [1.0, NAVY],
                    ],

                    # Explica a métrica da cor.
                    colorbar=dict(
                        title="Frequência<br>(pedidos)",
                        thickness=12,
                    ),

                    # Realça cada ponto contra o fundo branco.
                    line=dict(
                        color=WHITE,
                        width=1.5,
                    ),

                    # Permite visualizar sobreposição.
                    opacity=0.85,
                ),

                # Inclui métricas secundárias no tooltip.
                customdata=fieis[
                    [
                        "customer_id",
                        "faturamento_total",
                        "frequencia",
                    ]
                ],

                # Tooltip detalhado.
                hovertemplate=(
                    "<b>Cliente %{customdata[0]}</b><br>"
                    "Diversidade: %{x:.0f} categorias<br>"
                    "Ticket médio: R$ %{y:,.2f}<br>"
                    "Faturamento: R$ %{customdata[1]:,.2f}<br>"
                    "Frequência: %{customdata[2]:,.0f} pedidos"
                    "<extra></extra>"
                ),
            )
        )

        # Mediana vertical: separa menor e maior diversidade dentro do grupo elite.
        fig.add_vline(
            x=mediana_diversidade,
            line_width=1.4,
            line_dash="dash",
            line_color=MUTED,
            annotation_text="Mediana de diversidade",
            annotation_position="top left",
        )

        # Mediana horizontal: separa menor e maior Ticket Médio do Top 10.
        fig.add_hline(
            y=mediana_ticket,
            line_width=1.4,
            line_dash="dash",
            line_color=MUTED,
            annotation_text="Mediana de Ticket",
            annotation_position="bottom right",
        )

        # Destaca o quadrante de maior interesse estratégico.
        fig.add_annotation(
            x=0.99,
            y=0.98,
            xref="paper",
            yref="paper",
            text="⭐ Alto Ticket<br>+ Alta Diversidade",
            showarrow=False,
            xanchor="right",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.88)",
            bordercolor=GOLD,
            borderwidth=1,
            font=dict(
                color=NAVY,
                size=11,
            ),
        )

        # Realça o cliente de maior Ticket Médio, que é o líder do ranking.
        lider = fieis.loc[fieis["ticket_medio"].idxmax()]

        fig.add_annotation(
            x=float(lider["diversidade_categorias"]),
            y=float(lider["ticket_medio"]),
            text=f"🏆 Líder: {lider['customer_id']}",
            showarrow=True,
            arrowhead=2,
            ax=30,
            ay=-35,
            bgcolor=WHITE,
            bordercolor=GOLD,
            borderwidth=1,
            font=dict(
                color=NAVY,
                size=11,
            ),
        )

        # Aplica padrão visual do dashboard.
        estilo_figura(fig, 430)

        # Nomeia os eixos.
        fig.update_xaxes(
            title="Diversidade de Categorias",
            dtick=1,
        )

        fig.update_yaxes(
            title="Ticket Médio (R$)",
            tickprefix="R$ ",
        )

        # Não há necessidade de legenda para uma única série.
        fig.update_layout(
            showlegend=False,
        )

        # Renderiza a matriz.
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

        # Adiciona guia rápido de interpretação.
        st.caption(
            "💡 Leitura: clientes no quadrante superior direito combinam "
            "Ticket Médio elevado com maior diversidade. O tamanho representa "
            "faturamento e a cor representa frequência."
        )

with c2:
    st.markdown("#### 🧩 Categorias Preferidas dos Top 10")
    cats = buscar_categorias_elite(data_inicio, data_fim, tuple(canais))
    if cats.empty:
        vazio("Sem categorias disponíveis porque não há grupo elite elegível no período.")
    else:
        plot = cats.sort_values("quantidade_itens", ascending=True)
        fig = px.bar(plot, x="quantidade_itens", y="categoria", orientation="h", custom_data=["percentual_grupo"])
        fig.update_traces(
            marker_color=NAVY,
            hovertemplate="<b>%{y}</b><br>Itens: %{x:,.0f}<br>% do grupo elite: %{customdata[0]:.1f}%<extra></extra>",
        )
        estilo_figura(fig)
        fig.update_xaxes(title="Quantidade de Itens")
        fig.update_yaxes(title="")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# =============================================================================
# LOJAS FÍSICAS
# =============================================================================

st.markdown('<div class="section-title">Operação das Lojas Físicas</div>', unsafe_allow_html=True)
p1, p2 = st.columns(2)
pos = buscar_pos(data_inicio, data_fim, tuple(canais))

with p1:
    st.markdown("#### 🏪 Média de Vendas por Dia da Semana")
    if pos.empty:
        vazio("O filtro global exclui Loja Física (pos). Inclua o canal pos para visualizar este indicador.")
    else:
        menor = pos["media_vendas"].min()
        cores = [RED if valor == menor else NAVY for valor in pos["media_vendas"]]
        fig = go.Figure(
            go.Bar(
                x=pos["dia_semana"],
                y=pos["media_vendas"],
                marker_color=cores,
                customdata=pos[["dias_calendario", "dias_com_venda", "dias_sem_venda"]],
                hovertemplate="<b>%{x}</b><br>Média: R$ %{y:,.2f}<br>Dias calendário: %{customdata[0]:,.0f}<br>Dias com venda: %{customdata[1]:,.0f}<br>Dias sem venda: %{customdata[2]:,.0f}<extra></extra>",
            )
        )
        estilo_figura(fig)
        fig.update_yaxes(title="Média de Vendas (R$)")
        fig.update_xaxes(title="")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

with p2:
    st.markdown("#### 📆 Taxa de Dias sem Venda")
    if pos.empty:
        vazio("O filtro global exclui Loja Física (pos). Inclua o canal pos para visualizar este indicador.")
    else:
        fig = go.Figure(
            go.Bar(
                x=pos["dia_semana"],
                y=pos["taxa_dias_sem_venda"],
                marker_color=GOLD,
                customdata=pos[["dias_sem_venda", "dias_calendario"]],
                hovertemplate="<b>%{x}</b><br>Taxa sem venda: %{y:.1f}%<br>Dias sem venda: %{customdata[0]:,.0f}<br>Dias calendário: %{customdata[1]:,.0f}<extra></extra>",
            )
        )
        estilo_figura(fig)
        fig.update_yaxes(title="% de Dias sem Venda", ticksuffix="%")
        fig.update_xaxes(title="")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# =============================================================================
# RODAPÉ METODOLÓGICO
# =============================================================================

st.divider()
st.caption(
    "📌 Regras: período baseado em orders.placed_at • pedidos com DISTINCT • clientes fiéis exigem diversidade ≥ 13 categorias • "
    "indicadores POS usam calendário + LEFT JOIN + COALESCE(0) • lucro/prejuízo só é exibido quando existe custo/profit verificável • matrizes de clientes usam medianas do grupo para formar quadrantes analíticos."
)
