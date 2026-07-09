// 验证 ComfyUI HTTP API 在浏览器外能用（node 兜底，不依赖 Python）。
// 用法: node tests/curl_smoke.js [base_url]

const http = require("http");
const { URL } = require("url");

const BASE = process.argv[2] || "http://127.0.0.1:8188";

function req(method, urlPath, body) {
    return new Promise((resolve, reject) => {
        const u = new URL(BASE + urlPath);
        const data = body ? JSON.stringify(body) : null;
        const opts = {
            method,
            hostname: u.hostname,
            port: u.port,
            path: u.pathname + u.search,
            headers: {
                "Content-Type": "application/json",
                "Content-Length": data ? Buffer.byteLength(data) : 0,
            },
            timeout: 15000,
        };
        const r = http.request(opts, (res) => {
            let buf = "";
            res.on("data", (c) => (buf += c));
            res.on("end", () => {
                let parsed;
                try { parsed = JSON.parse(buf); }
                catch { parsed = buf.slice(0, 300); }
                resolve({ status: res.statusCode, body: parsed });
            });
        });
        r.on("timeout", () => { r.destroy(new Error("timeout")); });
        r.on("error", reject);
        if (data) r.write(data);
        r.end();
    });
}

async function main() {
    console.log("=" .repeat(60));
    console.log("curl_smoke against " + BASE);
    console.log("=" .repeat(60));

    // [1/3] 探活 /system_stats
    console.log("\n[1/3] GET /system_stats");
    let stats;
    try {
        stats = await req("GET", "/system_stats");
        console.log("  status:", stats.status);
        if (stats.status !== 200) {
            console.log("  body:", JSON.stringify(stats.body).slice(0, 200));
            process.exit(1);
        }
    } catch (e) {
        console.log("  FAIL: " + e.message);
        console.log("  -> 启动 ComfyUI 启动器.exe 等 :8188 起");
        process.exit(1);
    }

    // [2/3] /prompt 入队一个最小 workflow
    console.log("\n[2/3] POST /prompt (minimal workflow)");
    const wf = {
        "30":  { "inputs": { "image": "halfbody.png" }, "class_type": "LoadImage" },
        "360": { "inputs": { "text": "smoke" },         "class_type": "CLIPTextEncode" },
    };
    const q = await req("POST", "/prompt", { prompt: wf, client_id: "curl-smoke" });
    console.log("  status:", q.status);
    console.log("  body:", JSON.stringify(q.body).slice(0, 300));
    if (q.status !== 200 || !q.body.prompt_id) {
        console.log("  FAIL: /prompt 返了非预期响应");
        process.exit(2);
    }

    // [3/3] 轮询一次
    console.log("\n[3/3] GET /history/" + q.body.prompt_id.slice(0, 8) + "...");
    await new Promise((r) => setTimeout(r, 2000));
    const h = await req("GET", "/history/" + q.body.prompt_id);
    console.log("  status:", h.status);
    console.log("  body:", JSON.stringify(h.body).slice(0, 300));

    console.log("\n" + "=" .repeat(60));
    console.log("curl_smoke OK");
    console.log("=" .repeat(60));
}

main().catch((e) => { console.error("UNCAUGHT:", e); process.exit(99); });