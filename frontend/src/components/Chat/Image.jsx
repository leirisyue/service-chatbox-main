import { useState } from "react";
import { convertGDriveUrl } from "../../utils/gdrive";

export default function ImageWithFallback({ imageUrl, caption }) {
  console.log("🚀 ~ ImageWithFallback ~ imageUrl:", imageUrl);
  const [error, setError] = useState(false);

  const src = convertGDriveUrl(imageUrl);
  console.log("🚀 ~ ImageWithFallback ~ src:", src);

  if (!imageUrl || error) {
    return (
      <div
        style={{
          background:
            "linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%)",
          height: 150,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 8,
          color: "white",
          fontSize: "3rem",
        }}
      >
        🧱
      </div>
    );
  }

  return (
    <figure style={{ margin: 0 }}>
      <img
        src={src}
        alt={caption || "image"}
        style={{
          width: "100%",
          borderRadius: 8,
          objectFit: "cover",
        }}
        onError={() => setError(true)}
        loading="lazy"
      />
      {caption && (
        <figcaption style={{ fontSize: 12, marginTop: 4 }}>
          {caption.slice(0, 40)}
        </figcaption>
      )}
    </figure>
  );
}
