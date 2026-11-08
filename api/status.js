export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const now = new Date();
  const confidence = 0.965 + (Math.sin(now.getTime() / 5000) * 0.025);

  return res.status(200).json({
    ok: true,
    presence: "present_high",
    mode: "study",
    focus_active: false,
    phones_connected: 1,
    cloud_mode: true,
    hub: "Vercel Edge Cloud",
    confidence: parseFloat(confidence.toFixed(4)),
    owner: "Surya",
    eco_mode: false,
    camera_paused: false,
    stay_awake: false,
    timestamp: now.toISOString()
  });
}
