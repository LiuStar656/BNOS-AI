/**
 * BNOS 桥接 — 客户端半边（browser classic script，跑在 dsh web 渲染层）
 *
 * 在会话视图环中注册「BNOS」标签页：一个自包含的聊天面板。
 *  - 发送：POST /bnos/api/send（宿主写 gui_input.json）
 *  - 轮询：GET  /bnos/api/poll（宿主判新后返回 reply）
 *  - request_id 过滤：只接受与当前在途请求匹配的回复（对齐 MessageManager）
 *  - pending 处理：<pending/> 回执替换式续写，完成后收尾
 *  - 标签剥离：<silent/> / <pending/> 不显示
 */
window.__ModuleLoader__.load({
	id: "@bnos/bridge",
	factory: (require) => {
		const module = { exports: {} };
		const exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

		const react = require("react");
		const { jsx, jsxs } = require("react/jsx-runtime");

		const NS = "bnos-bridge";

		const CSS = [
			".bnos-chat-root{display:flex;flex-direction:column;height:100%;box-sizing:border-box;min-height:0}",
			".bnos-chat-head{flex:none;display:flex;align-items:center;gap:8px;padding:10px 16px;border-bottom:1px solid var(--dsw-alias-border-l2);color:var(--dsw-alias-label-secondary);font-size:12px}",
			".bnos-chat-body{flex:1;min-height:0;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;box-sizing:border-box}",
			".bnos-chat-empty{color:var(--dsw-alias-label-tertiary);font-size:13px;text-align:center;margin:40px 0}",
			".bnos-chat-msg{display:flex;flex-direction:column;gap:4px;max-width:80%}",
			".bnos-chat-msg.user{align-self:flex-end;align-items:flex-end}",
			".bnos-chat-msg.assistant{align-self:flex-start;align-items:flex-start}",
			".bnos-chat-role{font-size:11px;color:var(--dsw-alias-label-tertiary)}",
			".bnos-chat-text{padding:8px 12px;border-radius:10px;font-size:13px;line-height:20px;white-space:pre-wrap;word-break:break-word;color:var(--dsw-alias-label-primary)}",
			".bnos-chat-msg.user .bnos-chat-text{background:var(--dsw-alias-interactive-bg-active,#3b6bd6);color:#fff}",
			".bnos-chat-msg.assistant .bnos-chat-text{background:var(--dsw-alias-bg-module-platform,#26272c);border:1px solid var(--dsw-alias-border-l2)}",
			".bnos-chat-pending{font-size:11px;color:var(--dsw-alias-label-tertiary)}",
			".bnos-chat-error{padding:6px 12px;font-size:12px;color:#ff8a8a;background:rgba(255,80,80,.12);border-radius:8px;margin:0 16px}",
			".bnos-chat-input{flex:none;display:flex;align-items:center;gap:8px;padding:10px 16px;border-top:1px solid var(--dsw-alias-border-l2)}",
			".bnos-chat-input input{flex:1;min-width:0;background:var(--dsw-alias-bg-module-platform);border:1px solid var(--dsw-alias-border-l2);border-radius:8px;color:var(--dsw-alias-label-primary);font-size:13px;line-height:20px;padding:8px 12px;outline:none}",
			".bnos-chat-input input:focus{border-color:var(--dsw-alias-interactive-border-focus)}",
			".bnos-chat-input button{flex:none;background:var(--dsw-alias-interactive-bg-active,#3b6bd6);border:none;border-radius:8px;color:#fff;font-size:13px;padding:8px 16px;cursor:pointer}",
			".bnos-chat-input button:disabled{opacity:.5;cursor:default}"
		].join("");

		function ensureCss() {
			if (typeof document === "undefined") return;
			const tagId = NS + "/client.css";
			if (document.querySelector("style[data-plugin-css=" + JSON.stringify(tagId) + "]")) return;
			const tag = document.createElement("style");
			tag.dataset.plugin = NS;
			tag.dataset.pluginCss = tagId;
			tag.textContent = CSS;
			document.head.appendChild(tag);
		}

		function stripTags(text) {
			return String(text || "").replace(/<silent\/?>|<pending\/?>/g, "");
		}

		function BnosChatView() {
			const [messages, setMessages] = react.useState([]);
			const [input, setInput] = react.useState("");
			const [busy, setBusy] = react.useState(false);
			const [error, setError] = react.useState("");
			const scrollRef = react.useRef(null);
			const convIdRef = react.useRef("default");
			// 在途请求 id：只接受与它匹配的 reply；置空后忽略一切旧回执
			const ridRef = react.useRef("");

			react.useEffect(() => {
				try {
					let id = localStorage.getItem("bnos.conversation_id");
					if (!id) {
						id = Math.random().toString(16).slice(2, 10);
						localStorage.setItem("bnos.conversation_id", id);
					}
					convIdRef.current = id;
				} catch {
					convIdRef.current = "default";
				}
			}, []);

			react.useEffect(() => {
				const timer = setInterval(async () => {
					if (!ridRef.current) return;
					try {
						const res = await fetch("/bnos/api/poll");
						const data = await res.json();
						if (!data || !data.ok || !data.reply) return;
						const r = data.reply;
						// request_id 过滤：丢弃不匹配的过期回复
						if (r.request_id && r.request_id !== ridRef.current) return;
						const text = stripTags(r.content);
						setMessages((ms) => {
							const last = ms[ms.length - 1];
							if (last && last.role === "assistant" && last.pending) {
								return [...ms.slice(0, -1), { role: "assistant", text, pending: r.pending }];
							}
							return [...ms, { role: "assistant", text, pending: r.pending }];
						});
						if (!r.pending) {
							ridRef.current = "";
							setBusy(false);
						}
					} catch {
						/* 宿主临时不可达，下一轮再试 */
					}
				}, 300);
				return () => clearInterval(timer);
			}, []);

			react.useEffect(() => {
				const el = scrollRef.current;
				if (el) el.scrollTop = el.scrollHeight;
			}, [messages]);

			const send = async () => {
				const text = input.trim();
				if (!text || busy) return;
				const rid = Math.random().toString(16).slice(2, 10);
				ridRef.current = rid;
				setMessages((ms) => [...ms, { role: "user", text, pending: false }]);
				setInput("");
				setBusy(true);
				setError("");
				try {
					const res = await fetch("/bnos/api/send", {
						method: "POST",
						headers: { "content-type": "application/json" },
						body: JSON.stringify({
							content: text,
							conversation_id: convIdRef.current,
							request_id: rid,
						}),
					});
					const data = await res.json();
					if (!data || !data.ok) {
						setError((data && data.error) || "发送失败");
						ridRef.current = "";
						setBusy(false);
					}
				} catch (e) {
					setError("无法连接桥接服务");
					ridRef.current = "";
					setBusy(false);
				}
			};

			return jsxs("div", {
				className: "bnos-chat-root",
				children: [
					jsx("div", { className: "bnos-chat-head", children: "BNOS 聊天 · 桥接 dsh web（AAA 日常模式）" }),
					jsx("div", {
						className: "bnos-chat-body",
						ref: scrollRef,
						children: messages.length === 0
							? jsx("div", { className: "bnos-chat-empty", children: "发送消息开始与 AAA 对话" })
							: messages.map((m, i) => jsxs("div", {
								className: "bnos-chat-msg " + (m.role === "user" ? "user" : "assistant"),
								key: i,
								children: [
									jsx("div", { className: "bnos-chat-role", children: m.role === "user" ? "你" : "AAA" }),
									jsx("div", { className: "bnos-chat-text", children: m.text || " " }),
									m.pending ? jsx("div", { className: "bnos-chat-pending", children: "任务执行中…" }) : null
								]
							}))
					}),
					error ? jsx("div", { className: "bnos-chat-error", children: error }) : null,
					jsxs("form", {
						className: "bnos-chat-input",
						onSubmit: (e) => { e.preventDefault(); send(); },
						children: [
							jsx("input", {
								value: input,
								onChange: (e) => setInput(e.target.value),
								placeholder: busy ? "等待 AAA 回复…" : "输入消息，回车发送",
								disabled: busy,
								autoFocus: true,
								spellCheck: false
							}),
							jsx("button", { type: "submit", disabled: busy || !input.trim(), children: busy ? "等待回复…" : "发送" })
						]
					})
				]
			});
		}

		function apply(ctx) {
			ensureCss();
			ctx.slots.inject("conversation.view", () => ctx.slots.register({
				name: "conversation.view",
				id: "bnos-chat",
				order: 40,
				label: () => "BNOS"
			}, BnosChatView), "bnos-bridge: BNOS chat view");
		}

		exports.apply = apply;
		exports.inject = ["slots"];
		return module.exports;
	}
});
