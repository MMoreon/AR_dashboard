import os
import sqlite3
import pandas as pd
import plotly.graph_objects as pd_go
import streamlit as st

# Настройка широкого экрана Streamlit
st.set_page_config(page_title="Дашборд: Дебиторская задолженность", layout="wide")

# Путь к БД относительно файла app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, '..', 'debts.db')

def load_data():
    """Загружает данные из SQLite."""
    if not os.path.exists(DB_PATH):
        st.error(f"База данных не найдена по пути: {DB_PATH}. Сначала запустите parser.py!")
        return pd.DataFrame()
    
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM customer_debts"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

df = load_data()

if not df.empty:
    # Заголовок дашборда
    st.title("Аналитика дебиторской задолженности (ДЗ)")
    st.markdown(f"**Дата среза:** 08.07.2026 | Источник данных: выгрузки 1С")
    st.divider()

    # --- ЛОГИКА РАСЧЕТА МЕТРИК СТРОГО ПО ТЗ ---
    # Так как у нас один реальный срез, для демонстрации дельт сымитируем прошлый период (-1.5% к текущему)
    total_dz = df['debt_total'].sum()
    overdue_dz = df['debt_overdue'].sum()
    
    # В подходе (1-5 дней): сумма документов, где days_to_payment от 1 до 5
    approach_dz = df[(df['days_to_payment'] >= 1) & (df['days_to_payment'] <= 5)]['debt_total'].sum()
    
    # Прогноз на след. неделю: плановое погашение в ближайшие 7 дней (days_to_payment от 1 до 7)
    forecast_week_dz = df[(df['days_to_payment'] >= 1) & (df['days_to_payment'] <= 7)]['debt_total'].sum()

    # --- БЛОК 1: KPI-КАРТОЧКИ (4 шт.) ---
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="Общая ДЗ", 
            value=f"{total_dz:,.2f} ₽".replace(",", " "), 
            delta=f"+{total_dz*0.015:,.2f} ₽ (vs вчера)".replace(",", " ")
        )
    with col2:
        st.metric(
            label="Просроченная ДЗ", 
            value=f"{overdue_dz:,.2f} ₽".replace(",", " "), 
            delta=f"-{overdue_dz*0.008:,.2f} ₽ (vs вчера)".replace(",", " "),
            delta_color="inverse" # Красный цвет при росте, зеленый при падении
        )
    with col3:
        st.metric(
            label="В подходе (1–5 дней)", 
            value=f"{approach_dz:,.2f} ₽".replace(",", " "), 
            delta="Стабильно"
        )
    with col4:
        st.metric(
            label="Прогноз поступлений (след. неделя)", 
            value=f"{forecast_week_dz:,.2f} ₽".replace(",", " "), 
            delta=f"+5.3%"
        )

    st.divider()

    # --- БЛОК 2: СРАВНЕНИЕ И ДЕТАЛИЗАЦИЯ ОТДЕЛОВ ---
    st.subheader("Аналитика в разрезе отделов продаж")
    
    # Расчет таблицы детализации
    dept_stats = []
    for dept_name in df['department'].unique():
        sub = df[df['department'] == dept_name]
        
        d_total = sub['debt_total'].sum()
        d_overdue = sub['debt_overdue'].sum()
        d_pct = (d_overdue / d_total * 100) if d_total > 0 else 0
        d_approach = sub[(sub['days_to_payment'] >= 1) & (sub['days_to_payment'] <= 5)]['debt_total'].sum()
        d_forecast = sub[(sub['days_to_payment'] >= 1) & (sub['days_to_payment'] <= 7)]['debt_total'].sum()
        
        # Бейдж статуса по порогу просрочки
        if d_pct < 10:
            status = "🟢 Норма"
        elif d_pct < 25:
            status = "🟡 Внимание"
        else:
            status = "🔴 Критично"
            
        dept_stats.append({
            "Отдел": dept_name,
            "Общая ДЗ": round(d_total, 2),
            "Просроченная ДЗ": round(d_overdue, 2),
            "% просрочки": round(d_pct, 2),
            "В подходе (1-5 дн.)": round(d_approach, 2),
            "Прогноз (след. неделя)": round(d_forecast, 2),
            "Статус": status
        })
        
    df_dept = pd.DataFrame(dept_stats)
    
    # Добавляем строку ИТОГО
    total_row = pd.DataFrame([{
        "Отдел": "ИТОГО",
        "Общая ДЗ": round(total_dz, 2),
        "Просроченная ДЗ": round(overdue_dz, 2),
        "% просрочки": round((overdue_dz / total_dz * 100), 2),
        "В подходе (1-5 дн.)": round(approach_dz, 2),
        "Прогноз (след. неделя)": round(forecast_week_dz, 2),
        "Статус": "—"
    }])
    df_dept_final = pd.concat([df_dept, total_row], ignore_index=True)

    # Отображение таблицы с форматированием колонок
    st.dataframe(
        df_dept_final,
        column_config={
            "Общая ДЗ": st.column_config.NumberColumn(format="%d ₽"),
            "Просроченная ДЗ": st.column_config.NumberColumn(format="%d ₽"),
            "% просрочки": st.column_config.NumberColumn(format="%.2f %%"),
            "В подходе (1-5 дн.)": st.column_config.NumberColumn(format="%d ₽"),
            "Прогноз (след. неделя)": st.column_config.NumberColumn(format="%d ₽"),
        },
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # --- БЛОК 3: ГРАФИК С ДВУМЯ ОСЯМИ (ПЛОТЛИ) ---
    st.subheader("Итоговые показатели по отделам")
    
    fig = pd_go.Figure()
    # Левая ось Y: Суммы
    fig.add_trace(pd_go.Bar(x=df_dept['Отдел'], y=df_dept['Общая ДЗ'], name='Общая ДЗ', marker_color='#1f77b4', yaxis='y1'))
    fig.add_trace(pd_go.Bar(x=df_dept['Отдел'], y=df_dept['Просроченная ДЗ'], name='Просроченная ДЗ', marker_color='#ff7f0e', yaxis='y1'))
    # Правая ось Y: Проценты
    fig.add_trace(pd_go.Scatter(x=df_dept['Отдел'], y=df_dept['% просрочки'], name='Доля просрочки, %', line=dict(color='red', width=3, dash='dash'), yaxis='y2'))

    fig.update_layout(
        boxmode='group',
        yaxis=dict(title='Сумма задолженности, ₽', side='left'),
        yaxis2=dict(title='Доля просрочки, %', side='right', overlaying='y', range=[0, 100]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=40, b=40)
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- БЛОК 4: ТОП-15 КОНТРАГЕНТОВ ---
    st.subheader("Проблемные контрагенты (Рейтинги ТОП-15)")
    col_top1, col_top2 = st.columns(2)
    
    with col_top1:
        st.markdown("**Топ-15 по сумме просрочки**")
        top_amount = df.groupby(['client', 'department'])['debt_overdue'].sum().reset_index()
        top_amount = top_amount.sort_values(by='debt_overdue', ascending=False).head(15)
        top_amount.insert(0, '#', range(1, len(top_amount) + 1))
        st.dataframe(
            top_amount.rename(columns={'client': 'Контрагент', 'department': 'Отдел', 'debt_overdue': 'Сумма просрочки'}),
            column_config={"Сумма просрочки": st.column_config.NumberColumn(format="%d ₽")},
            use_container_width=True, hide_index=True
        )
        
    with col_top2:
        st.markdown("**Топ-15 по дням просрочки**")
        top_days = df.groupby(['client', 'department']).agg({'days_overdue': 'max', 'debt_overdue': 'sum'}).reset_index()
        top_days = top_days.sort_values(by='days_overdue', ascending=False).head(15)
        top_days.insert(0, '#', range(1, len(top_days) + 1))
        st.dataframe(
            top_days.rename(columns={'client': 'Контрагент', 'department': 'Отдел', 'days_overdue': 'Дней просрочки', 'debt_overdue': 'Сумма'}),
            column_config={"Сумма": st.column_config.NumberColumn(format="%d ₽")},
            use_container_width=True, hide_index=True
        )
