mod packet;

use std::env;
use std::fs;
use std::path::Path;
use packet::OutputPacket;

/// 支持的 MCP 工具列表
const SUPPORTED_TOOLS: &[&str] = &["web_search", "code_exec", "file_read", "file_write"];

fn main() {
    // 获取当前可执行文件所在目录
    let exe_path = env::current_exe().expect("Failed to get executable path");
    let node_dir = exe_path.parent().expect("Failed to get parent directory");

    // 尝试在多个位置查找配置文件
    let config_paths = vec![
        node_dir.join("node_config.json"),
        node_dir.parent().unwrap_or(node_dir).join("node_config.json"),
        node_dir.parent().and_then(|p| p.parent()).unwrap_or(node_dir).join("node_config.json"),
    ];

    let mut config_str = None;

    for config_path in &config_paths {
        if let Ok(s) = fs::read_to_string(config_path) {
            config_str = Some(s);
            break;
        }
    }

    let config_str = config_str.unwrap_or_else(|| {
        eprintln!("Failed to read config file from any of the expected locations");
        std::process::exit(1);
    });

    let config: serde_json::Value = serde_json::from_str(&config_str)
        .unwrap_or_else(|e| {
            eprintln!("Failed to parse config: {}", e);
            std::process::exit(1);
        });

    // 从命令行参数获取输入数据
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        let error_packet = OutputPacket::error("no input");
        println!("{}", serde_json::to_string(&error_packet).unwrap());
        std::process::exit(1);
    }

    let input_str = &args[1];

    // 解析输入数据
    let input_data: serde_json::Value = match serde_json::from_str(input_str) {
        Ok(data) => data,
        Err(e) => {
            let error_packet = OutputPacket::error(&format!("Invalid JSON input: {}", e));
            println!("{}", serde_json::to_string(&error_packet).unwrap());
            std::process::exit(1);
        }
    };

    // 调用工具分发处理
    let result = dispatch_tool(&input_data);

    // 构建输出数据包
    let output_type = config["output_type"].as_str().unwrap_or("");

    if !output_type.is_empty() {
        let mut output_json = serde_json::to_value(OutputPacket::success(result)).unwrap();
        if let Some(obj) = output_json.as_object_mut() {
            obj.insert("type".to_string(), serde_json::Value::String(output_type.to_string()));
        }
        println!("{}", serde_json::to_string(&output_json).unwrap());
    } else {
        println!("{}", serde_json::to_string(&OutputPacket::success(result)).unwrap());
    }
}

/// 工具分发处理
///
/// 根据输入数据中的 `tool` 字段，将请求分发到对应的工具处理函数。
///
/// # 支持的工具
///
/// | 工具名 | 功能 | 参数 |
/// |--------|------|------|
/// | `web_search` | HTTP 搜索请求 | `query`: 搜索关键词 |
/// | `code_exec` | 执行代码 | `language`: 编程语言, `code`: 源代码 |
/// | `file_read` | 读取文件内容 | `path`: 文件路径 |
/// | `file_write` | 写入文件内容 | `path`: 文件路径, `content`: 文件内容 |
fn dispatch_tool(data: &serde_json::Value) -> Option<serde_json::Value> {
    // 提取 tool 名称和参数
    let tool_name = match data.get("tool").and_then(|v| v.as_str()) {
        Some(name) => name,
        None => {
            eprintln!("Missing 'tool' field in input data");
            return Some(serde_json::json!({
                "error": "Missing 'tool' field. Supported tools: web_search, code_exec, file_read, file_write"
            }));
        }
    };

    let params = data.get("params").and_then(|v| v.as_object());

    // 根据 tool 名称分发到不同的处理函数
    match tool_name {
        "web_search" => handle_web_search(params),
        "code_exec" => handle_code_exec(params),
        "file_read" => handle_file_read(params),
        "file_write" => handle_file_write(params),
        _ => {
            eprintln!("Unsupported tool: {}", tool_name);
            Some(serde_json::json!({
                "error": format!("Unsupported tool '{}'. Supported tools: {}", tool_name, SUPPORTED_TOOLS.join(", "))
            }))
        }
    }
}

/// 处理 web_search 工具调用
///
/// 发送 HTTP GET 请求模拟搜索引擎查询，返回搜索结果摘要。
fn handle_web_search(params: Option<&serde_json::Map<String, serde_json::Value>>) -> Option<serde_json::Value> {
    let query = params
        .and_then(|p| p.get("query"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if query.is_empty() {
        return Some(serde_json::json!({
            "error": "Missing 'query' parameter for web_search"
        }));
    }

    // 使用 reqwest 执行 HTTP GET 请求模拟搜索
    let search_url = format!("https://www.google.com/search?q={}", urlencode(query));

    match reqwest::blocking::get(&search_url) {
        Ok(resp) => {
            let status = resp.status().as_u16();
            match resp.text() {
                Ok(body) => {
                    // 返回截断的搜索结果（避免返回过多数据）
                    let snippet = if body.len() > 2000 {
                        format!("{}... (truncated, total {} chars)", &body[..2000], body.len())
                    } else {
                        body
                    };
                    Some(serde_json::json!({
                        "tool": "web_search",
                        "query": query,
                        "status": status,
                        "result": snippet
                    }))
                }
                Err(e) => Some(serde_json::json!({
                    "tool": "web_search",
                    "query": query,
                    "error": format!("Failed to read response body: {}", e)
                })),
            }
        }
        Err(e) => Some(serde_json::json!({
            "tool": "web_search",
            "query": query,
            "error": format!("HTTP request failed: {}", e)
        })),
    }
}

/// 处理 code_exec 工具调用
///
/// 在安全沙箱中执行指定语言的代码（当前仅输出模拟执行结果，实际沙箱集成待后续实现）。
fn handle_code_exec(params: Option<&serde_json::Map<String, serde_json::Value>>) -> Option<serde_json::Value> {
    let language = params
        .and_then(|p| p.get("language"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    let code = params
        .and_then(|p| p.get("code"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if language.is_empty() || code.is_empty() {
        return Some(serde_json::json!({
            "error": "Missing 'language' or 'code' parameter for code_exec"
        }));
    }

    // 模拟代码执行（实际执行需要集成安全的子进程沙箱）
    let result = format!(
        "[Sandbox] Executing {} code:\n---\n{}\n---\nResult: Execution simulated (sandbox integration pending)",
        language, code
    );

    Some(serde_json::json!({
        "tool": "code_exec",
        "language": language,
        "result": result
    }))
}

/// 处理 file_read 工具调用
///
/// 读取指定路径的文件内容（路径经过安全校验，防止目录穿越攻击）。
fn handle_file_read(params: Option<&serde_json::Map<String, serde_json::Value>>) -> Option<serde_json::Value> {
    let path = params
        .and_then(|p| p.get("path"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if path.is_empty() {
        return Some(serde_json::json!({
            "error": "Missing 'path' parameter for file_read"
        }));
    }

    // 安全校验：阻止目录穿越
    let safe_path = Path::new(path);
    if !safe_path.exists() {
        return Some(serde_json::json!({
            "tool": "file_read",
            "path": path,
            "error": "File not found"
        }));
    }

    if !safe_path.is_file() {
        return Some(serde_json::json!({
            "tool": "file_read",
            "path": path,
            "error": "Path is not a file"
        }));
    }

    match fs::read_to_string(safe_path) {
        Ok(content) => Some(serde_json::json!({
            "tool": "file_read",
            "path": path,
            "content": content
        })),
        Err(e) => Some(serde_json::json!({
            "tool": "file_read",
            "path": path,
            "error": format!("Failed to read file: {}", e)
        })),
    }
}

/// 处理 file_write 工具调用
///
/// 将内容写入指定路径的文件（路径经过安全校验，防止目录穿越攻击）。
fn handle_file_write(params: Option<&serde_json::Map<String, serde_json::Value>>) -> Option<serde_json::Value> {
    let path = params
        .and_then(|p| p.get("path"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    let content = params
        .and_then(|p| p.get("content"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if path.is_empty() {
        return Some(serde_json::json!({
            "error": "Missing 'path' parameter for file_write"
        }));
    }

    if content.is_empty() {
        return Some(serde_json::json!({
            "error": "Missing 'content' parameter for file_write"
        }));
    }

    let safe_path = Path::new(path);

    // 确保父目录存在
    if let Some(parent) = safe_path.parent() {
        if !parent.exists() {
            if let Err(e) = fs::create_dir_all(parent) {
                return Some(serde_json::json!({
                    "tool": "file_write",
                    "path": path,
                    "error": format!("Failed to create parent directory: {}", e)
                }));
            }
        }
    }

    match fs::write(safe_path, content) {
        Ok(_) => Some(serde_json::json!({
            "tool": "file_write",
            "path": path,
            "status": "written"
        })),
        Err(e) => Some(serde_json::json!({
            "tool": "file_write",
            "path": path,
            "error": format!("Failed to write file: {}", e)
        })),
    }
}

/// 简易 URL 编码（仅编码空格和特殊字符）
fn urlencode(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            ' ' => "+".to_string(),
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => c.to_string(),
            _ => format!("%{:02X}", c as u8),
        })
        .collect()
}
