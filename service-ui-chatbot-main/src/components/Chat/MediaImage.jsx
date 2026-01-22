import React, { useEffect, useState } from "react";
import { createMedia } from "../../services/api";

export default function MediaImage({ imageUrl, alt }) {
  const [mediaUrl, setMediaUrl] = useState(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!imageUrl) return;

    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(false);
        setMediaUrl(null);
        const res = await createMedia(imageUrl);
        if (!cancelled && res?.url) {
          setMediaUrl(res.url); 
        }
      } catch (err) {
        console.error("Load image failed:", err);
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [imageUrl]);

  if (loading) {
    return <div className="image-loading">Loading image...</div>;
  }

  if (error) {
    return <div className="image-placeholder">🧱 Image unavailable</div>;
  }

  if (!mediaUrl) {
    return null;
  }

  return (
    <img
      src={mediaUrl}
      alt={alt || ""}
      loading="lazy"
      style={{
        width: "100%",
        maxHeight: 200,
        objectFit: "contain",
        borderRadius: 8,
      }}
      onError={() => setError(true)}
    />
  );
}
