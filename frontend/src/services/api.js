import axios from 'axios';

const API_URL = process.env.API_URL || 'http://localhost:8000';
const API_URL_CHATBOT = process.env.API_URL_CHATBOT || 'http://localhost:8080';

const api = axios.create({
  baseURL: API_URL,
  timeout: 30000,
});

const api_Chatbot = axios.create({
  baseURL: API_URL_CHATBOT,
  timeout: 30000,
});

// Chat endpoints
export const sendMessage = async (sessionId, message, context) => {
  const response = await api.post('/chat', {
    session_id: sessionId,
    message,
    context
  });
  return response.data;
};

export const queryChat = async (min_score, text, top_k)=>{
    const response = await api_Chatbot.post('/api/query', {
    min_score,
    text,
    top_k
  });
  return response.data;
}

export const searchByImage = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await api.post('/search-image', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

// Import endpoints
export const importProducts = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await api.post('/import/products', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const importMaterials = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await api.post('/import/materials', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const importProductMaterials = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await api.post('/import/product-materials', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

// Classification endpoints
export const classifyProducts = async () => {
  const response = await api.post('/classify-products');
  return response.data;
};

export const classifyMaterials = async () => {
  const response = await api.post('/classify-materials');
  return response.data;
};

// Embedding endpoints
export const generateEmbeddings = async () => {
  const response = await api.post('/generate-embeddings');
  return response.data;
};

export const generateMaterialEmbeddings = async () => {
  const response = await api.post('/generate-material-embeddings');
  return response.data;
};

// Debug endpoints
export const getDebugInfo = async () => {
  try {
    const [products, materials] = await Promise.all([
      api.get('/debug/products'),
      api.get('/debug/materials')
    ]);
    
    return {
      products: products.data,
      materials: materials.data
    };
  } catch (error) {
    console.error('Error fetching debug info:', error);
    throw error;
  }
};