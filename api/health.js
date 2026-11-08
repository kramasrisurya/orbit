export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  return res.status(200).json({
    status: "healthy",
    service: "ORBIT Cloud Edge",
    version: "1.0.0",
    timestamp: new Date().toISOString(),
    docs: "https://github.com/kramasrisurya/orbit"
  });
}
