import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 本地开发代理：把 /chat、/history 等后端请求转发到已部署的云端 Agent。
// 说明：
//   1. 本地 `npm run dev` 只启动前端（Vite，默认 5173 端口）；
//   2. 后端 Agent 已部署在 EdgeOne Makers 云端，此处用代理把接口请求转发过去；
//   3. EdgeOne 预览访问靠 eo_token/eo_time Cookie 鉴权（首次 302 种 Cookie），
//      这里在转发请求时直接把 token 写进 Cookie 头，避免 302 跳转导致 POST body 丢失；
//   4. token 从 .env 的 EO_TOKEN / EO_TIME 读取（.env 已在 .gitignore，不会泄露）。
//      失效后到 Makers 控制台点「预览」拿新链接，更新 .env 即可。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  const cloudOrigin =
    env.EO_CLOUD_ORIGIN || 'https://openai-agent-starter-python-py-m9oxnhxl.edgeone.cool'
  const eoToken = env.EO_TOKEN || ''
  const eoTime = env.EO_TIME || ''
  const eoCookie = `eo_token=${eoToken}; eo_time=${eoTime}`

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/chat': {
          target: cloudOrigin,
          changeOrigin: true,
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              const existing = proxyReq.getHeader('cookie')
              proxyReq.setHeader(
                'cookie',
                existing ? `${existing}; ${eoCookie}` : eoCookie,
              )
            })
          },
        },
        '/stop': { target: cloudOrigin, changeOrigin: true },
        '/history': { target: cloudOrigin, changeOrigin: true },
        '/conversations': { target: cloudOrigin, changeOrigin: true },
        '/clear-history': { target: cloudOrigin, changeOrigin: true },
        '/delete-conversation': { target: cloudOrigin, changeOrigin: true },
      },
    },
  }
})
