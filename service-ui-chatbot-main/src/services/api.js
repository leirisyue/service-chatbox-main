import axios from 'axios';

const API_URL = process.env.API_URL || 'http://localhost:8000';
const API_URL_CHATBOT = process.env.API_URL_CHATBOT || 'http://localhost:8080';

const api = axios.create({
  baseURL: API_URL,
  // timeout: 60000,
});

const api_Chatbot = axios.create({
  baseURL: API_URL_CHATBOT,
  // timeout: 60000,
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

export const queryChat = async (min_score, text, top_k) => {
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

export const searchImageWithText = async (file, text, sessionId) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('description', text);
  formData.append('session_id', sessionId);

  const response = await api.post('/search-image-with-text', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

// Tracking endpoints
export const trackView = async (sessionId, productHeadcode) => {
  try {
    await api.post('/track/view', {
      session_id: sessionId,
      product_headcode: productHeadcode,
      interaction_type: 'view',
    });
  } catch (error) {
    console.error('Error tracking view:', error);
  }
};

export const trackReject = async (sessionId, productHeadcode) => {
  try {
    await api.post('/track/reject', {
      session_id: sessionId,
      product_headcode: productHeadcode,
      interaction_type: 'reject',
    });
  } catch (error) {
    console.error('Error tracking reject:', error);
  }
};

// Batch products operations
export const batchProducts = async (sessionId, productHeadcodes, operation) => {
  const response = await api.post('/batch/products', {
    product_headcodes: productHeadcodes,
    session_id: sessionId,
    operation,
  });
  return response.data;
};

// Export consolidated BOM report
export const exportBOMReport = async (sessionId, productHeadcodes) => {
  const response = await api.post(
    '/report/consolidated',
    {
      product_headcodes: productHeadcodes,
      session_id: sessionId,
    },
    {
      responseType: 'blob',
    }
  );

  return response.data; // Blob
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

export const createMedia = async (imageUrl) => {
  console.log('createMedia', imageUrl);
  const response = await api.post("/media", imageUrl);
  return response.data;
};

// Chat History endpoints
export const getChatSessionId = async (session_id) => {
  if (!session_id) return [];
  const response = await api.get(`/history/${session_id}`);
  return response.data;
};

export const getChatSessions = async (email) => {
  if (!email) return [];
  const response = await api.get(`/chat_histories/email/${email}`);
  return response.data;
};

export const getSessionHistory = async (email, sessionId) => {
  const response = await api.get(`/chat_histories/${email}/${sessionId}`);
  return response.data;
};

export const getMessagersHistory = async (sessionId) => {
  const response = await api.get(`/history/session_id/${sessionId}/messages`);
  return response.data;
}

// Rename session
export const renameSession = async (sessionId, newName) => {
  const response = await api.put(`/chat_histories/session/${sessionId}/rename`, {
    session_name: newName
  });
  return response.data;
};

// Delete session
export const deleteSession = async (sessionId) => {
  const response = await api.delete(`/chat_histories/session/${sessionId}`);
  return response.data;
};