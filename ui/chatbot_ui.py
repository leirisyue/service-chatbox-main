import streamlit as st
import requests
import uuid
import json
from io import BytesIO

API_URL = "http://127.0.0.1:8000"

# ========================================
# PAGE CONFIG
# ========================================

st.set_page_config(
    page_title="AA Corporation AI Assistant v4.0",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #64748B;
        text-align: center;
        margin-bottom: 2rem;
    }
    .user-msg {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 0.8rem 1.2rem;
        border-radius: 18px 18px 4px 18px;
        margin: 0.5rem 0 0.5rem auto;
        max-width: 70%;
        float: right;
        clear: both;
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
    }
    .bot-msg {
        background: white;
        color: #1f2937;
        padding: 0.8rem 1.2rem;
        border-radius: 18px 18px 18px 4px;
        margin: 0.5rem auto 0.5rem 0;
        max-width: 70%;
        float: left;
        clear: both;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }
    .product-card {
        background: white;
        border-radius: 12px;
        padding: 1rem;
        margin: 0.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        transition: transform 0.2s;
        border-left: 4px solid #667eea;
    }
    .product-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .material-card {
        background: #f0fdf4;
        border-radius: 12px;
        padding: 1rem;
        margin: 0.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        transition: transform 0.2s;
        border-left: 4px solid #10b981;
    }
    .material-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .price-badge {
        display: inline-block;
        background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
        color: white;
        padding: 0.3rem 0.8rem;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.9rem;
        margin-top: 0.5rem;
    }
    .version-badge {
        display: inline-block;
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        color: white;
        padding: 0.2rem 0.6rem;
        border-radius: 8px;
        font-size: 0.75rem;
        margin-left: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ========================================
# SESSION STATE
# ========================================

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

if "context" not in st.session_state:
    st.session_state.context = {
        "last_search_results": [],
        "current_products": [],
        "current_materials": [],
        "search_params": {}
    }

if "suggested_prompts" not in st.session_state:
    st.session_state.suggested_prompts = [
        "🔍 Tìm sản phẩm",
        "🧱 Tìm nguyên vật liệu", 
        "💰 Tính chi phí",
        "📋 Danh sách nhóm vật liệu"
    ]

# ========================================
# HELPER FUNCTIONS
# ========================================

def convert_gdrive_url_to_direct(url: str) -> str:
    """Convert Google Drive sharing URL to direct image URL"""
    if not url or 'drive.google.com' not in url:
        return url
    
    try:
        if '/file/d/' in url:
            file_id = url.split('/file/d/')[1].split('/')[0]
        elif 'id=' in url:
            file_id = url.split('id=')[1].split('&')[0]
        else:
            return url
        
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    except:
        return url

@st.cache_data(ttl=3600, show_spinner=False)
def load_image_from_url(url: str):
    """Tải ảnh từ URL server-side để tránh lỗi chặn của Google Drive"""
    if not url: 
        return None
    
    direct_url = convert_gdrive_url_to_direct(url)
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(direct_url, headers=headers, timeout=3)
        
        if response.status_code == 200:
            return BytesIO(response.content)
    except Exception:
        return None
    return None

def send_message(message: str):
    """Gửi tin nhắn đến backend"""
    try:
        response = requests.post(
            f"{API_URL}/chat",
            json={
                "session_id": st.session_state.session_id, 
                "message": message,
                "context": st.session_state.context
            },
            timeout=15
        )
        return response.json()
    except Exception as e:
        return {"response": f"⚠️ Lỗi kết nối: {str(e)}"}

def add_message(role: str, content: str, data=None):
    """Thêm tin nhắn vào history"""
    msg = {
        "role": role, 
        "content": content,
        "timestamp": str(uuid.uuid4())[:8]
    }
    if data:
        msg["data"] = data
    st.session_state.messages.append(msg)

def process_user_input(user_input: str):
    """Xử lý input từ user"""
    add_message("user", user_input)
    
    with st.spinner("🤔 Đang suy nghĩ..."):
        response = send_message(user_input)
        
        if response.get("context"):
            st.session_state.context.update(response["context"])
        
        if response.get("products"):
            st.session_state.context["current_products"] = response["products"]
            st.session_state.context["last_search_results"] = [p["headcode"] for p in response["products"]]
        
        if response.get("materials"):
            st.session_state.context["current_materials"] = response["materials"]
        
        add_message("bot", response.get("response", "Xin lỗi, tôi không hiểu."), data=response)
        
        if response.get("suggested_prompts"):
            st.session_state.suggested_prompts = response["suggested_prompts"]
    
    st.rerun()

# ========================================
# SIDEBAR
# ========================================

# ========================================
# SIDEBAR
# ========================================

with st.sidebar:
    st.markdown('<div style="text-align: center;"><h2>⚙️ Quản Trị Hệ Thống</h2><span class="version-badge">V4.5</span></div>', unsafe_allow_html=True)
    
    st.divider()
    
    st.subheader("📤 Import & Phân Loại")
    
    # ----------------------------------------
    # 1. SẢN PHẨM (PRODUCTS)
    # ----------------------------------------
    with st.expander("📦 Sản Phẩm", expanded=False):
        st.caption("**Required:** headcode, id_sap, product_name")
        uploaded_products = st.file_uploader("Chọn CSV Products", type=['csv'], key="products")
        
        # Nút Import
        if uploaded_products and st.button("Import Sản Phẩm", key="imp_prod", type="primary"):
            with st.spinner("Đang import dữ liệu..."):
                try:
                    uploaded_products.seek(0)
                    files = {"file": uploaded_products}
                    response = requests.post(f"{API_URL}/import/products", files=files, timeout=60)
                    if response.status_code == 200:
                        result = response.json()
                        st.success(result["message"])
                        
                        # Hiển thị số lượng cần phân loại
                        pending = result.get("pending_classification", 0)
                        if pending > 0:
                            st.warning(f"⚠️ Có {pending} sản phẩm chưa phân loại. Hãy dùng nút bên dưới.")
                        
                        if result.get("errors"):
                            with st.expander("Xem lỗi import"):
                                for err in result['errors']:
                                    st.error(err)
                except Exception as e:
                    st.error(f"Lỗi kết nối: {e}")

        st.markdown("---")
        
        # Nút Auto Classify (Chạy Batch)
        if st.button("🤖 AI Auto-Classify Products"):
            status_box = st.empty()
            progress_bar = st.progress(0)
            
            try:
                # Vòng lặp chạy cho đến khi hết sản phẩm chưa phân loại
                while True:
                    response = requests.post(f"{API_URL}/classify-products", timeout=60)
                    if response.status_code != 200:
                        st.error("Lỗi khi gọi API phân loại")
                        break
                        
                    res = response.json()
                    classified = res.get('classified', 0)
                    remaining = res.get('remaining', 0)
                    total = res.get('total', 0)
                    
                    if classified == 0 and remaining == 0:
                        status_box.success("✅ Đã phân loại xong toàn bộ!")
                        progress_bar.progress(100)
                        break
                    
                    if classified == 0: # Không còn gì để làm hoặc lỗi
                        status_box.info(res.get("message", "Hoàn tất."))
                        break

                    # Cập nhật trạng thái
                    status_box.info(f"⏳ Đang xử lý... Còn lại: {remaining}")
                    
                    # Tính % tiến độ (ước lượng)
                    if total > 0:
                        percent = min(1.0, (total - remaining) / total)
                        progress_bar.progress(percent)
                    
            except Exception as e:
                st.error(f"Lỗi: {e}")

    # ----------------------------------------
    # 2. VẬT LIỆU (MATERIALS)
    # ----------------------------------------
    with st.expander("🧱 Vật Liệu", expanded=False):
        st.caption("**Required:** id_sap, material_name, material_group")
        uploaded_materials = st.file_uploader("Chọn CSV Materials", type=['csv'], key="materials")
        
        if uploaded_materials and st.button("Import Vật Liệu", key="imp_mat", type="primary"):
            with st.spinner("Đang import..."):
                try:
                    uploaded_materials.seek(0)
                    files = {"file": uploaded_materials}
                    response = requests.post(f"{API_URL}/import/materials", files=files, timeout=60)
                    if response.status_code == 200:
                        result = response.json()
                        st.success(result["message"])
                        
                        pending = result.get("pending_classification", 0)
                        if pending > 0:
                            st.warning(f"⚠️ Có {pending} vật liệu chưa phân loại.")
                            
                        if result.get("errors"):
                            with st.expander("Xem lỗi import"):
                                for err in result['errors']:
                                    st.error(err)
                except Exception as e:
                    st.error(f"Lỗi: {e}")

        st.markdown("---")
        
        # Nút Auto Classify Materials
        if st.button("🤖 AI Classify Materials"):
            status_box_mat = st.empty()
            
            try:
                while True:
                    response = requests.post(f"{API_URL}/classify-materials", timeout=60)
                    if response.status_code != 200:
                        break
                    
                    res = response.json()
                    classified = res.get('classified', 0)
                    remaining = res.get('remaining', 0)
                    
                    if classified == 0 and remaining == 0:
                        status_box_mat.success("✅ Đã phân loại xong!")
                        break
                    
                    if classified == 0:
                        status_box_mat.info(res.get("message"))
                        break
                        
                    status_box_mat.info(f"⏳ Đang xử lý... Còn lại: {remaining}")
                    
            except Exception as e:
                st.error(f"Lỗi: {e}")

    # ----------------------------------------
    # 3. ĐỊNH MỨC (BOM) - CẬP NHẬT V4.5
    # ----------------------------------------
    with st.expander("📊 Định Mức (BOM)", expanded=False):
        st.caption("**Required:** product_headcode")
        st.caption("**Optional:** material_id_sap, quantity")
        st.caption("ℹ️ *Tự động tạo vật liệu thiếu & Fix lỗi ID đuôi .0*")
        
        uploaded_pm = st.file_uploader("Chọn CSV BOM", type=['csv'], key="pm")
        
        if uploaded_pm and st.button("Import BOM", key="imp_pm", type="primary"):
            with st.spinner("Đang xử lý BOM (V4.5)..."):
                try:
                    uploaded_pm.seek(0)
                    files = {"file": uploaded_pm}
                    response = requests.post(f"{API_URL}/import/product-materials", files=files, timeout=120)
                    
                    if response.status_code == 200:
                        result = response.json()
                        st.success(result["message"])
                        
                        # Hiển thị thống kê chi tiết V4.5
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.metric("Imported", result.get("imported", 0))
                            st.metric("Skipped", result.get("skipped", 0), help="Bỏ qua do thiếu mã vật liệu")
                        with col_b:
                            st.metric("Auto-Created", result.get("auto_created_materials", 0), help="Vật liệu mới được tự động tạo")
                            st.metric("Total Rows", result.get("total_rows", 0))
                        
                        if result.get("errors"):
                            with st.expander("⚠️ Xem chi tiết lỗi"):
                                for err in result['errors']:
                                    st.error(err)
                except Exception as e:
                    st.error(f"Lỗi: {e}")
    
    st.divider()
    
    # ----------------------------------------
    # 4. VECTOR EMBEDDINGS
    # ----------------------------------------
    st.subheader("🧠 Vector Embeddings")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.caption("**Sản phẩm**")
        if st.button("⚡ Products", use_container_width=True, type="secondary"):
            with st.spinner("Embedding Products..."):
                try:
                    response = requests.post(f"{API_URL}/generate-embeddings", timeout=300)
                    if response.status_code == 200:
                        st.success(response.json()['message'])
                except Exception as e:
                    st.error(f"Lỗi: {e}")
    
    with col2:
        st.caption("**Vật liệu**")
        if st.button("⚡ Materials", use_container_width=True, type="secondary"):
            with st.spinner("Embedding Materials..."):
                try:
                    response = requests.post(f"{API_URL}/generate-material-embeddings", timeout=300)
                    if response.status_code == 200:
                        st.success(response.json()['message'])
                except Exception as e:
                    st.error(f"Lỗi: {e}")
    
    st.divider()
    
    # ----------------------------------------
    # 5. DEBUG INFO
    # ----------------------------------------
    with st.expander("🔍 Debug Info"):
        if st.button("Refresh Info"):
            try:
                prod = requests.get(f"{API_URL}/debug/products", timeout=5).json()
                mat = requests.get(f"{API_URL}/debug/materials", timeout=5).json()
                
                st.markdown(f"**Products:** {prod['total_products']} ({prod['coverage_percent']}%)")
                st.markdown(f"**Materials:** {mat['total_materials']} ({mat['coverage_percent']}%)")
            except:
                st.warning("Server Offline")

    st.divider()
    
    if st.button("🔄 Reset Chat Session", use_container_width=True):
        st.session_state.messages = []
        st.session_state.context = {
            "last_search_results": [],
            "current_products": [],
            "current_materials": [],
            "search_params": {}
        }
        st.rerun()




# ========================================
# MAIN CONTENT
# ========================================

st.markdown('<div class="main-header">🏢 AA Corporation AI Assistant<span class="version-badge">V4.0</span></div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Trợ Lý AI Nội Thất Thông Minh - Hỗ trợ Sản phẩm & Vật liệu</div>', unsafe_allow_html=True)

# Welcome message
if not st.session_state.messages:
    add_message("bot", "👋 Xin chào! Tôi là trợ lý AI của **AA Corporation** (Phiên bản 4.0).\n\n"
                      "Tôi có thể giúp bạn:\n"
                      "• 🔍 **Tìm kiếm sản phẩm** (bằng mô tả hoặc hình ảnh)\n"
                      "• 🧱 **Tìm kiếm nguyên vật liệu** (gỗ, da, đá, vải...)\n"
                      "• 📋 **Xem định mức vật liệu** của sản phẩm\n"
                      "• 💰 **Tính chi phí** sản phẩm (NVL + Nhân công + Lợi nhuận)\n"
                      "• 🔗 **Tra cứu** vật liệu được dùng ở sản phẩm/dự án nào\n"
                      "• 📈 **Xem lịch sử giá** vật liệu\n\n"
                      "**🆕 Tính năng mới V4.0:**\n"
                      "• 🤖 AI tự động phân loại sản phẩm/vật liệu\n"
                      "• 📊 Lưu lịch sử truy vấn để học\n"
                      "• ⚡ Import CSV dễ dàng hơn\n\n"
                      "Hãy chọn một trong các gợi ý bên dưới hoặc gõ câu hỏi của bạn!")

# Chat container
chat_container = st.container()

with chat_container:
    for idx, message in enumerate(st.session_state.messages):
        role = message["role"]
        content = message["content"]
        
        if role == "user":
            st.markdown(f'<div class="user-msg">👤 {content}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="bot-msg">🤖 {content}</div>', unsafe_allow_html=True)
            
            # HIỂN THỊ SẢN PHẨM
            if message.get("data", {}).get("products"):
                products = message["data"]["products"]
                
                st.markdown("---")
                st.markdown(f"### 📦 Kết quả tìm kiếm sản phẩm ({len(products)} sản phẩm)")
                
                cols = st.columns(3)
                for pidx, product in enumerate(products[:9]):
                    with cols[pidx % 3]:
                        with st.container():
                            product_name = product.get('product_name', 'N/A')[:50]
                            headcode = product.get('headcode', 'N/A')
                            category = product.get('category', 'N/A')
                            sub_category = product.get('sub_category', 'N/A')
                            material_primary = product.get('material_primary', 'N/A')
                            project = product.get('project', '')
                            
                            st.markdown(f"""
                            <div class="product-card">
                                <h4>{product_name}...</h4>
                                <p>🏷️ <b>{headcode}</b></p>
                                <p>📦 {category} - {sub_category}</p>
                                <p>🪵 {material_primary}</p>
                            """, unsafe_allow_html=True)
                            
                            if project:
                                st.markdown(f"<p>🗝️ Dự án: {project}</p>", unsafe_allow_html=True)
                            
                            st.markdown("</div>", unsafe_allow_html=True)
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.button("📋 Vật liệu", key=f"mat_{headcode}_{idx}_{pidx}", use_container_width=True):
                                    process_user_input(f"Phân tích nguyên vật liệu sản phẩm {headcode}")
                            with col2:
                                if st.button("💰 Chi phí", key=f"price_{headcode}_{idx}_{pidx}", use_container_width=True):
                                    process_user_input(f"Tính chi phí sản phẩm {headcode}")
            
            # HIỂN THỊ VẬT LIỆU
            if message.get("data", {}).get("materials"):
                materials = message["data"]["materials"]
                
                st.markdown("---")
                st.markdown(f"### 🧱 Kết quả tìm kiếm nguyên vật liệu ({len(materials)} vật liệu)")
                
                cols = st.columns(3)
                for midx, material in enumerate(materials[:9]):
                    with cols[midx % 3]:
                        with st.container():
                            image_data = None
                            if material.get('image_url'):
                                image_data = load_image_from_url(material['image_url'])
                            
                            if image_data:
                                st.image(image_data, use_container_width=True, caption=material.get('material_name', 'N/A')[:40])
                            else:
                                st.markdown("""
                                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%); 
                                                height: 150px; 
                                                display: flex; 
                                                align-items: center; 
                                                justify-content: center;
                                                border-radius: 8px;
                                                color: white;
                                                font-size: 3rem;">
                                        🧱
                                    </div>
                                """, unsafe_allow_html=True)
                            
                            material_name = material.get('material_name', 'N/A')[:40]
                            id_sap = material.get('id_sap', 'N/A')
                            material_group = material.get('material_group', 'N/A')
                            price = material.get('price', 0)
                            unit = material.get('unit', '')
                            
                            st.markdown(f"""
                            <div class="material-card">
                                <h4>{material_name}...</h4>
                                <p>🏷️ Mã SAP: <b>{id_sap}</b></p>
                                <p>📂 Nhóm: {material_group}</p>
                                <div class="price-badge">💰 {price:,.2f} VNĐ/{unit}</div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.button("🔍 Chi tiết", key=f"detail_{id_sap}_{idx}_{midx}", use_container_width=True):
                                    process_user_input(f"Chi tiết vật liệu {material_name}")
                            with col2:
                                if material.get('image_url'):
                                    st.link_button("🔗 Drive", material['image_url'], use_container_width=True)
                                else:
                                    st.caption("_Chưa có ảnh_")
            
            # HIỂN THỊ CHI TIẾT VẬT LIỆU + ẢNH LỚN
            if message.get("data", {}).get("material_detail"):
                mat_detail = message["data"]["material_detail"]
                
                st.markdown("---")
                st.markdown("### 🧱 Chi tiết nguyên vật liệu")
                
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    img_data = None
                    if mat_detail.get('image_url'):
                        img_data = load_image_from_url(mat_detail['image_url'])
                    
                    if img_data:
                        st.image(img_data, caption=mat_detail.get('material_name', 'N/A'), use_container_width=True)
                    else:
                        st.info("📷 Chưa có ảnh hoặc không thể tải ảnh")
                
                with col2:
                    material_name = mat_detail.get('material_name', 'N/A')
                    id_sap = mat_detail.get('id_sap', 'N/A')
                    material_group = mat_detail.get('material_group', 'N/A')
                    unit = mat_detail.get('unit', '')
                    
                    latest_price = message["data"].get("latest_price", 0)

                    st.markdown(f"""
                    **Tên:** {material_name}  
                    **Mã SAP:** `{id_sap}`  
                    **Nhóm:** {material_group}  
                    **Giá mới nhất:** {latest_price:,.2f} VNĐ/{unit}
                    """)
                    
                    if message["data"].get("stats"):
                        stats = message["data"]["stats"]
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.metric("Sản phẩm sử dụng", stats.get('product_count', 0))
                        with col_b:
                            st.metric("Dự án", stats.get('project_count', 0))
                    
                    if message["data"].get("price_history"):
                        price_history = message["data"]["price_history"]
                        if price_history and len(price_history) > 0:
                            st.markdown("#### 📈 Lịch sử giá (5 gần nhất):")
                            for ph in sorted(price_history, key=lambda x: x.get('date', ''), reverse=True)[:5]:
                                date = ph.get('date', 'N/A')
                                price = ph.get('price', 0)
                                st.caption(f"• **{date}**: {price:,.2f} VNĐ")
                
                if message["data"].get("used_in_products"):
                    used = message["data"]["used_in_products"]
                    
                    if len(used) > 0:
                        st.markdown("#### 🔗 Sản phẩm đang sử dụng:")
                        
                        for prod in used[:5]:
                            product_name = prod.get('product_name', 'N/A')
                            headcode = prod.get('headcode', 'N/A')
                            category = prod.get('category', 'N/A')
                            quantity = prod.get('quantity', 0)
                            unit = prod.get('unit', '')
                            
                            with st.expander(f"📦 {product_name} ({headcode})"):
                                st.markdown(f"""
                                - **Danh mục:** {category}
                                - **Số lượng:** {quantity} {unit}
                                """)
                                
                                if st.button(f"Xem chi phí {headcode}", key=f"cost_{headcode}_{idx}"):
                                    process_user_input(f"Tính chi phí sản phẩm {headcode}")

st.markdown('<div style="clear:both;"></div>', unsafe_allow_html=True)

# Suggested prompts
st.divider()
st.markdown("#### 💡 Gợi ý nhanh:")

cols = st.columns(4)
for idx, prompt in enumerate(st.session_state.suggested_prompts[:4]):
    with cols[idx]:
        if st.button(prompt, key=f"suggest_{idx}_{prompt[:10]}", use_container_width=True):
            process_user_input(prompt.split(" ", 1)[1] if " " in prompt else prompt)

# Chat input
st.divider()

col1, col2 = st.columns([5, 1])

with col1:
    user_input = st.text_input(
        "Nhập câu hỏi của bạn...",
        key="chat_input",
        placeholder="VD: Tìm bàn tròn gỗ sồi, hoặc Tìm gỗ làm bàn...",
        label_visibility="collapsed"
    )

with col2:
    send_btn = st.button("Gửi", use_container_width=True, type="primary")

# Image upload
st.divider()
uploaded_image = st.file_uploader(
    "📷 Hoặc upload ảnh sản phẩm để tìm kiếm", 
    type=['png', 'jpg', 'jpeg'], 
    label_visibility="collapsed"
)

if send_btn and user_input:
    process_user_input(user_input)

if uploaded_image:
    col1, col2 = st.columns([1, 3])
    
    with col1:
        st.image(uploaded_image, caption="Ảnh bạn upload", use_container_width=True)
    
    with col2:
        if st.button("🔍 Tìm sản phẩm tương tự", use_container_width=True, type="primary"):
            with st.spinner("🤖 Đang phân tích ảnh..."):
                try:
                    uploaded_image.seek(0)
                    
                    files = {"file": uploaded_image}
                    response = requests.post(
                        f"{API_URL}/search-image", 
                        files=files,
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        
                        add_message("user", "📷 [Đã upload ảnh]")
                        
                        bot_response = result.get("response", "Đã tìm kiếm theo ảnh")
                        
                        add_message(
                            "bot", 
                            bot_response,
                            data=result
                        )
                        
                        if result.get("products"):
                            st.session_state.context["current_products"] = result["products"]
                            st.session_state.context["last_search_results"] = [
                                p["headcode"] for p in result["products"]
                            ]
                        
                        if result.get("products"):
                            first_headcode = result["products"][0]["headcode"]
                            st.session_state.suggested_prompts = [
                                f"💰 Xem chi phí {first_headcode}",
                                f"📋 Phân tích vật liệu {first_headcode}",
                                "🔍 Tìm sản phẩm khác"
                            ]
                        
                        st.rerun()
                    else:
                        st.error(f"Lỗi server: {response.status_code}")
                
                except Exception as e:
                    st.error(f"Đã xảy ra lỗi khi xử lý ảnh: {str(e)}")