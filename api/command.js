export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const body = req.body || {};
  const action = body.action || "none";

  const response = {
    ok: true,
    success: true,
    action: action,
    timestamp: new Date().toISOString()
  };

  if (action === 'toggle_eco') {
    response.eco_mode = body.enabled !== undefined ? body.enabled : true;
  } else if (action === 'toggle_camera') {
    response.paused = body.paused !== undefined ? body.paused : true;
  } else if (action === 'toggle_stay_awake') {
    response.stay_awake = body.stay_awake !== undefined ? body.stay_awake : true;
  } else if (action === 'take_snapshot') {
    response.path = `orbit_snapshot_${Date.now()}.jpg`;
    response.message = "Snapshot captured successfully";
  } else if (action === 'set_mode') {
    response.mode = body.mode || 'study';
  }

  return res.status(200).json(response);
}
