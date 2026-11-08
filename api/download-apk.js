export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');

  if (req.method === 'OPTIONS') return res.status(200).end();

  // Redirect to GitHub Actions workflow artifact or repo releases
  return res.redirect(302, 'https://github.com/kramasrisurya/orbit/actions');
}
