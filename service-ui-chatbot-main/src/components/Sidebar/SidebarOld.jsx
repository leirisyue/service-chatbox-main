import { useState } from 'react';
import {
  classifyMaterials, classifyProducts, generateEmbeddings,
  generateMaterialEmbeddings,
  getDebugInfo, importMaterials,
  importProductMaterials, importProducts
} from '../../services/api';
import './Sidebar.css';

function Sidebar({ sessionId, onResetChat }) {
  const [importResults, setImportResults] = useState({});
  const [isProcessing, setIsProcessing] = useState(false);
  const [debugInfo, setDebugInfo] = useState(null);

  const handleFileUpload = async (endpoint, file, type) => {
    if (!file) {
      alert('Vui lòng chọn file');
      return;
    }

    setIsProcessing(true);
    try {
      let response;
      switch(endpoint) {
        case 'products':
          response = await importProducts(file);
          break;
        case 'materials':
          response = await importMaterials(file);
          break;
        case 'product-materials':
          response = await importProductMaterials(file);
          break;
        default:
          return;
      }
      
      setImportResults(prev => ({
        ...prev,
        [type]: response
      }));
      
      if (response.message) {
        alert(response.message);
      }
    } catch (error) {
      console.error('Import error:', error);
      alert('Lỗi import: ' + error.message);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleClassification = async (type) => {
    setIsProcessing(true);
    try {
      let response;
      if (type === 'products') {
        response = await classifyProducts();
      } else {
        response = await classifyMaterials();
      }
      
      if (response.message) {
        alert(response.message);
      }
    } catch (error) {
      console.error('Classification error:', error);
      alert('Lỗi phân loại: ' + error.message);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleGenerateEmbeddings = async (type) => {
    setIsProcessing(true);
    try {
      let response;
      if (type === 'products') {
        response = await generateEmbeddings();
      } else {
        response = await generateMaterialEmbeddings();
      }
      
      if (response.message) {
        alert(response.message);
      }
    } catch (error) {
      console.error('Embeddings error:', error);
      alert('Lỗi tạo embeddings: ' + error.message);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDebugInfo = async () => {
    try {
      const info = await getDebugInfo();
      setDebugInfo(info);
    } catch (error) {
      console.error('Debug error:', error);
      alert('Lỗi lấy thông tin debug');
    }
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h2>⚙️ Quản Trị Hệ Thống</h2>
        <span className="version-badge" style={{textAlign: 'center'}}>V1.0</span>
      </div>
      
      {/* <div className="sidebar-section"> */}
        {/* <h3>📤 Import & Phân Loại</h3> */}
        
        {/* Products Import */}
        {/* <div className="sidebar-card">
          <h4>📦 Sản Phẩm</h4>
          <p className="help-text">Required: headcode, id_sap, product_name</p>
          <input
            type="file"
            id="products-upload"
            accept=".csv"
            onChange={(e) => {
              const file = e.target.files[0];
              if (file) {
                handleFileUpload('products', file, 'products');
              }
            }}
            disabled={isProcessing}
          />
          <button
            className="btn-primary"
            onClick={() => handleClassification('products')}
            disabled={isProcessing}
          >
            🤖 AI Auto-Classify Products
          </button>
          
          {importResults.products && (
            <div className="result-box">
              <p>{importResults.products.message}</p>
              {importResults.products.pending_classification > 0 && (
                <p className="warning-text">
                  ⚠️ Có {importResults.products.pending_classification} sản phẩm chưa phân loại
                </p>
              )}
            </div>
          )}
        </div> */}

        {/* Materials Import */}
        {/* <div className="sidebar-card">
          <h4>🧱 Vật Liệu</h4>
          <p className="help-text">Required: id_sap, material_name, material_group</p>
          <input
            type="file"
            id="materials-upload"
            accept=".csv"
            onChange={(e) => {
              const file = e.target.files[0];
              if (file) {
                handleFileUpload('materials', file, 'materials');
              }
            }}
            disabled={isProcessing}
          />
          <button
            className="btn-primary"
            onClick={() => handleClassification('materials')}
            disabled={isProcessing}
          >
            🤖 AI Classify Materials
          </button>
        </div> */}

        {/* BOM Import */}
        {/* <div className="sidebar-card">
          <h4>📊 Định Mức (BOM)</h4>
          <p className="help-text">Required: product_headcode</p>
          <p className="help-text">Optional: material_id_sap, quantity</p>
          <p className="help-text">ℹ️ Tự động tạo vật liệu thiếu & Fix lỗi ID đuôi .0</p>
          <input
            type="file"
            id="bom-upload"
            accept=".csv"
            onChange={(e) => {
              const file = e.target.files[0];
              if (file) {
                handleFileUpload('product-materials', file, 'bom');
              }
            }}
            disabled={isProcessing}
          />
          
          {importResults.bom && (
            <div className="stats-grid">
              <div className="stat">
                <span className="stat-label">Imported</span>
                <span className="stat-value">{importResults.bom.imported || 0}</span>
              </div>
              <div className="stat">
                <span className="stat-label">Auto-Created</span>
                <span className="stat-value">{importResults.bom.auto_created_materials || 0}</span>
              </div>
            </div>
          )}
        </div> */}
      {/* </div> */}

      {/* <div className="sidebar-section">
        <h3>🧠 Vector Embeddings</h3>
        <div className="button-group">
          <button
            className="btn-secondary"
            onClick={() => handleGenerateEmbeddings('products')}
            disabled={isProcessing}
          >
            ⚡ Products
          </button>
          <button
            className="btn-secondary"
            onClick={() => handleGenerateEmbeddings('materials')}
            disabled={isProcessing}
          >
            ⚡ Materials
          </button>
        </div>
      </div> */}

      {/* <div className="sidebar-section">
        <h3>🔍 Debug Info</h3>
        <button
          className="btn-secondary"
          onClick={handleDebugInfo}
          disabled={isProcessing}
        >
          Refresh Info
        </button>
        
        {debugInfo && (
          <div className="debug-info">
            <p><strong>Products:</strong> {debugInfo.products?.total_products || 0} ({debugInfo.products?.coverage_percent || 0}%)</p>
            <p><strong>Materials:</strong> {debugInfo.materials?.total_materials || 0} ({debugInfo.materials?.coverage_percent || 0}%)</p>
          </div>
        )}
      </div> */}

      <div className="sidebar-footer">
        <button
          className="btn-reset"
          onClick={onResetChat}
          disabled={isProcessing}
        >
          🔄 Reset Chat Session
        </button>
      </div>
    </div>
  );
}

export default Sidebar;