// Applies the saved theme before the app renders (no flash). A file, not inline: the CSP allows only 'self' scripts.
try {
  var t = localStorage.getItem('dwhcr.theme');
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
} catch (e) {
  /* storage unavailable */
}
