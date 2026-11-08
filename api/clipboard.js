export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  if (req.method === 'POST') {
    const text = req.body?.text || '';
    return res.status(200).json({
      ok: true,
      message: "Synced to mobile clipboard relay",
      length: text.length
    });
  }

  return res.status(200).json({
    text: "ORBIT Ambient Awareness System deployed on Vercel"
  });
}
