
export function convertGDriveUrl(url) {
  if (!url) return null;
  if ( !url.includes('drive.google.com')) return url;

  try {
    let fileId = null;

    if (url.includes('/file/d/')) {
      fileId = url.split('/file/d/')[1].split('/')[0];
    } else if (url.includes('id=')) {
      fileId = url.split('id=')[1].split('&')[0];
    }

    return fileId
      ? `https://lh3.googleusercontent.com/d/${fileId}`
      : url;
  } catch {
    return url;
  }
}
