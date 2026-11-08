export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  return res.status(200).json([
    {
      type: "PRESENCE_CHANGED",
      source: "cloud_edge",
      timestamp: new Date().toISOString(),
      payload: { state: "present_high", confidence: 0.98 }
    },
    {
      type: "MODE_CHANGED",
      source: "cloud_edge",
      timestamp: new Date().toISOString(),
      payload: { mode: "study" }
    }
  ]);
}
