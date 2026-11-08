export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  return res.status(200).json({
    ok: true,
    message: "File received by ORBIT Cloud AirDrop Bridge",
    target: req.query.target || "laptop",
    timestamp: new Date().toISOString()
  });
}
