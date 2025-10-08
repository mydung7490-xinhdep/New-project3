import streamlit as st
import pandas as pd
import numpy as np
from google import genai
from google.genai.errors import APIError
import docx # Cần cài đặt: pip install python-docx
import json
import io

# --- Cấu hình Trang Streamlit ---
st.set_page_config(
    page_title="App Đánh giá Phương án Kinh doanh (CAPEX)",
    layout="wide"
)

st.title("Ứng dụng Đánh giá Phương án Kinh doanh 📈")
st.caption("Sử dụng Gemini AI để trích xuất thông số và tính toán hiệu quả dự án.")

# Cấu trúc JSON Schema bắt buộc cho Gemini (Bước 1)
PROJECT_INFO_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "Investment_Capital": {"type": "NUMBER", "description": "Vốn đầu tư ban đầu (Initial Investment), đơn vị tiền tệ, phải là số dương."},
        "Project_Lifetime": {"type": "INTEGER", "description": "Dòng đời dự án tính bằng số năm."},
        "Annual_Revenue": {"type": "NUMBER", "description": "Doanh thu hàng năm dự kiến (dạng số, không có ký tự đơn vị)."},
        "Annual_Cost_Opex": {"type": "NUMBER", "description": "Chi phí hoạt động hàng năm (trừ Khấu hao), dạng số, không có ký tự đơn vị."},
        "WACC": {"type": "NUMBER", "description": "Chi phí sử dụng vốn bình quân WACC hoặc Lãi suất chiết khấu dự án (ví dụ: 0.1 cho 10%)."},
        "Tax_Rate": {"type": "NUMBER", "description": "Thuế suất thuế thu nhập doanh nghiệp (ví dụ: 0.2 cho 20%)."}
    },
    "required": ["Investment_Capital", "Project_Lifetime", "Annual_Revenue", "Annual_Cost_Opex", "WACC", "Tax_Rate"]
}

# --- HÀM TRÍCH XUẤT DỮ LIỆU TỪ WORD (Sử dụng AI) ---
@st.cache_data(show_spinner="Đang đọc file Word...")
def read_docx_content(uploaded_file):
    """Đọc nội dung văn bản thô từ file .docx."""
    try:
        doc = docx.Document(io.BytesIO(uploaded_file.read()))
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return "\n".join(full_text)
    except Exception as e:
        return f"Lỗi đọc file: {e}"

def extract_project_info(document_text, api_key):
    """Gọi Gemini API với JSON Schema để trích xuất các thông số tài chính."""
    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash'
        
        system_prompt = (
            "Bạn là trợ lý trích xuất dữ liệu tài chính. "
            "Phân tích văn bản đính kèm và trích xuất 6 thông số tài chính bắt buộc (Vốn đầu tư, Dòng đời, Doanh thu, Chi phí, WACC, Thuế suất). "
            "CHỈ được trả về kết quả dưới dạng JSON theo schema đã cung cấp. "
            "Đảm bảo tất cả các giá trị đều là số (Không có đơn vị, dấu phẩy, hay ký tự tiền tệ)."
        )

        prompt = f"Trích xuất các thông số tài chính bắt buộc từ tài liệu sau:\n\n---\n{document_text[:20000]}" # Giới hạn nội dung
        
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "system_instruction": system_prompt,
                "response_mime_type": "application/json",
                "response_schema": PROJECT_INFO_SCHEMA
            }
        )
        
        # Parse JSON output
        json_string = response.text.strip()
        return json.loads(json_string)

    except APIError as e:
        st.error(f"Lỗi gọi Gemini API: {e}. Vui lòng kiểm tra Khóa API và giới hạn sử dụng.")
        return None
    except json.JSONDecodeError:
        st.error("Lỗi: AI trả về định dạng JSON không hợp lệ. Vui lòng thử lại hoặc chỉnh sửa nội dung file Word để dễ trích xuất hơn.")
        return None
    except Exception as e:
        st.error(f"Đã xảy ra lỗi không xác định: {e}")
        return None

# --- HÀM TÍNH TOÁN DÒNG TIỀN VÀ CHỈ SỐ (Bước 2 & 3) ---
@st.cache_data
def calculate_cash_flow_metrics(info):
    """Xây dựng bảng dòng tiền và tính toán NPV, IRR, PP, DPP."""
    
    # 1. Trích xuất thông số
    I0 = info['Investment_Capital']
    N = info['Project_Lifetime']
    R = info['Annual_Revenue']
    C = info['Annual_Cost_Opex']
    WACC = info['WACC']
    Tax = info['Tax_Rate']
    
    # Giả định: Khấu hao (D) = Vốn đầu tư / Dòng đời (Linear Depreciation)
    D = I0 / N
    
    years = np.arange(N + 1)
    
    # Bảng Dòng tiền (Cash Flow Statement)
    df_cf = pd.DataFrame({'Năm': years})
    
    # Năm 0 (Chỉ có Vốn đầu tư)
    df_cf.loc[0, 'Doanh thu (R)'] = 0
    df_cf.loc[0, 'Chi phí (C+D)'] = 0
    df_cf.loc[0, 'Dòng tiền Thuần (CF)'] = -I0
    
    # Năm 1 đến N
    for y in years[1:]:
        # 1. EBIT = R - C - D
        EBIT = R - C - D
        # 2. EBT = EBIT (Vì không có lãi vay)
        EBT = EBIT
        # 3. Thuế
        Tax_Amount = EBT * Tax if EBT > 0 else 0
        # 4. EAT (Lợi nhuận sau thuế)
        EAT = EBT - Tax_Amount
        # 5. Dòng tiền Thuần (CF) = EAT + D + Vốn thu hồi (Salvage Value = 0)
        CF = EAT + D
        
        df_cf.loc[y, 'Doanh thu (R)'] = R
        df_cf.loc[y, 'Chi phí (C+D)'] = C + D
        df_cf.loc[y, 'Dòng tiền Thuần (CF)'] = CF
    
    # --- Tính toán Chỉ số Đánh giá ---
    cf_vector = df_cf['Dòng tiền Thuần (CF)'].values
    
    # 1. NPV (Net Present Value)
    npv_value = np.npv(WACC, cf_vector)
    
    # 2. IRR (Internal Rate of Return)
    try:
        irr_value = np.irr(cf_vector)
    except:
        irr_value = np.nan
        
    # 3. PP (Payback Period)
    cumulative_cf = np.cumsum(df_cf['Dòng tiền Thuần (CF)'])
    payback_index = np.where(cumulative_cf >= 0)[0]
    pp_value = years[payback_index[0]] if len(payback_index) > 0 else N # Nếu CF không bao giờ dương
    
    # 4. DPP (Discounted Payback Period)
    discount_factors = 1 / (1 + WACC)**years
    discounted_cf = df_cf['Dòng tiền Thuần (CF)'] * discount_factors
    cumulative_dcf = np.cumsum(discounted_cf)
    dpp_index = np.where(cumulative_dcf >= 0)[0]
    dpp_value = years[dpp_index[0]] if len(dpp_index) > 0 else N
    
    return df_cf, npv_value, irr_value, pp_value, dpp_value

# --- HÀM GỌI GEMINI CHO PHÂN TÍCH TÓM TẮT (Bước 4) ---
def get_ai_appraisal(metrics_data, api_key):
    """Gửi các chỉ số đánh giá cho Gemini để nhận xét."""
    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash'

        prompt = f"""
        Bạn là chuyên gia phân tích đầu tư và tài chính doanh nghiệp. Dựa trên các chỉ số hiệu quả dự án sau, hãy đưa ra một đánh giá khách quan, tóm tắt (khoảng 3 đoạn) về tính khả thi và rủi ro của dự án.
        Tiêu chuẩn đánh giá:
        - NPV > 0: Dự án khả thi.
        - IRR > WACC: Dự án khả thi.
        - PP/DPP < Dòng đời dự án: Thời gian thu hồi vốn hợp lý.

        Các chỉ số cần phân tích:
        {metrics_data}
        """

        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text

    except APIError as e:
        return f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API. Chi tiết lỗi: {e}"
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định: {e}"

# =================================================================
# =================== PHẦN GIAO DIỆN STREAMLIT ====================
# =================================================================

# Khởi tạo session state để lưu dữ liệu trích xuất
if 'project_info' not in st.session_state:
    st.session_state.project_info = None

# 1. Tải File Word
uploaded_file = st.file_uploader(
    "1. Tải file Word (.docx) chứa Phương án Kinh doanh/Dự án Đầu tư",
    type=['docx']
)

if uploaded_file is not None:
    st.info("File đã tải lên. Nhấn nút 'Lọc Dữ liệu bằng AI' để bắt đầu trích xuất.")
    
    # Nút bấm để thực hiện tạo tác lọc dữ liệu
    if st.button("Lọc Dữ liệu bằng AI (Bước 1)"):
        api_key = st.secrets.get("GEMINI_API_KEY")
        if not api_key:
            st.error("Lỗi: Không tìm thấy Khóa API 'GEMINI_API_KEY'. Vui lòng cấu hình trong Streamlit Secrets.")
        else:
            document_text = read_docx_content(uploaded_file)
            if not document_text.startswith("Lỗi đọc file"):
                with st.spinner('Đang gửi nội dung file cho AI để trích xuất thông số...'):
                    extracted_info = extract_project_info(document_text, api_key)
                    if extracted_info:
                        st.session_state.project_info = extracted_info
                        st.success("Trích xuất dữ liệu thành công!")
                    else:
                        st.session_state.project_info = None
                        
# 2. Hiển thị Thông tin đã trích xuất
if st.session_state.project_info:
    info = st.session_state.project_info
    
    st.subheader("2. Thông số Tài chính Trích xuất từ AI")
    
    # Định dạng hiển thị
    formatted_data = {
        'Chỉ tiêu': [
            'Vốn đầu tư (I₀)', 'Dòng đời dự án (Năm)', 'Doanh thu Hàng năm (R)', 
            'Chi phí Hàng năm (C_OPEX)', 'WACC/Lãi suất chiết khấu', 'Thuế suất (T)'
        ],
        'Giá trị': [
            f"{info.get('Investment_Capital', 0):,.0f}",
            f"{info.get('Project_Lifetime', 0):,.0f}",
            f"{info.get('Annual_Revenue', 0):,.0f}",
            f"{info.get('Annual_Cost_Opex', 0):,.0f}",
            f"{info.get('WACC', 0)*100:.2f}%",
            f"{info.get('Tax_Rate', 0)*100:.0f}%"
        ]
    }
    st.table(pd.DataFrame(formatted_data).set_index('Chỉ tiêu'))
    
    # 3. Xây dựng Bảng Dòng tiền và Tính Chỉ số
    try:
        df_cf, npv, irr, pp, dpp = calculate_cash_flow_metrics(info)
        
        st.subheader("3. Bảng Dòng tiền (Cash Flow Statement)")
        st.dataframe(
            df_cf.style.format({
                'Doanh thu (R)': '{:,.0f}',
                'Chi phí (C+D)': '{:,.0f}',
                'Dòng tiền Thuần (CF)': '{:,.0f}',
            }),
            hide_index=True,
            use_container_width=True
        )

        st.subheader("4. Các Chỉ số Đánh giá Hiệu quả Dự án")
        col_npv, col_irr, col_pp, col_dpp = st.columns(4)

        with col_npv:
            st.metric(
                label="Giá trị Hiện tại Thuần (NPV)",
                value=f"{npv:,.0f}",
                delta="Khả thi" if npv > 0 else "Không khả thi"
            )

        with col_irr:
            st.metric(
                label="Tỷ suất Sinh lời Nội bộ (IRR)",
                value=f"{irr*100:.2f}%",
                delta="Tốt" if irr > info['WACC'] else "Không đạt"
            )

        with col_pp:
            st.metric(
                label="Thời gian Hoàn vốn (PP)",
                value=f"{pp:.1f} năm"
            )
            
        with col_dpp:
            st.metric(
                label="Thời gian Hoàn vốn có Chiết khấu (DPP)",
                value=f"{dpp:.1f} năm"
            )
        
        # 5. Yêu cầu AI Phân tích Chỉ số
        st.subheader("5. Nhận xét Đánh giá Dự án (AI)")
        
        metrics_data_for_ai = pd.DataFrame({
            'Chỉ tiêu': ['WACC', 'NPV', 'IRR', 'PP', 'DPP', 'Dòng đời dự án'],
            'Giá trị': [
                f"{info['WACC']*100:.2f}%",
                f"{npv:,.0f}",
                f"{irr*100:.2f}%",
                f"{pp:.1f} năm",
                f"{dpp:.1f} năm",
                f"{info['Project_Lifetime']:.0f} năm"
            ]
        }).to_markdown(index=False)

        if st.button("Yêu cầu AI Phân tích Hiệu quả Dự án"):
            api_key = st.secrets.get("GEMINI_API_KEY")
            if api_key:
                with st.spinner('Đang gửi các chỉ số và chờ Gemini phân tích...'):
                    ai_result = get_ai_appraisal(metrics_data_for_ai, api_key)
                    st.markdown("**Kết quả Phân tích từ Gemini AI:**")
                    st.info(ai_result)
            else:
                st.error("Lỗi: Không tìm thấy Khóa API. Vui lòng cấu hình Khóa 'GEMINI_API_KEY' trong Streamlit Secrets.")

    except Exception as e:
        st.error(f"Lỗi tính toán: {e}. Vui lòng kiểm tra lại dữ liệu trích xuất.")
        st.caption("Chi tiết lỗi thường do giá trị WACC, Tax Rate không hợp lệ hoặc Dòng tiền không hội tụ để tính IRR.")

else:
    st.info("Tải file Word lên và sử dụng chức năng 'Lọc Dữ liệu bằng AI' để bắt đầu.")
