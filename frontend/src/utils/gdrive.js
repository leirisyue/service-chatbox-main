
export function convertGDriveUrl(url) {
  if (!url || !url.includes('drive.google.com')) return url;

  try {
    let fileId = null;

    if (url.includes('/file/d/')) {
      fileId = url.split('/file/d/')[1].split('/')[0];
    } else if (url.includes('id=')) {
      fileId = url.split('id=')[1].split('&')[0];
    }

    return fileId
      ? `https://drive.google.com/uc?export=view&id=${fileId}`
      : url;
  } catch {
    return url;
  }
}
