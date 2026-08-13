use std::env;
use std::fs;
use std::io::Write;
use std::path::Path;
use std::process::Command;
use std::thread;
use std::time::Duration;
use chrono::Local;

fn main() {
    println!("Starting node_rust_grok_hands listener...");

    // 自愈机制：检查环境
    if !check_and_fix_environment() {
        eprintln!("Environment check failed!");
        std::process::exit(1);
    }

    // 读取配置
    let config = read_config();

    // 检查是否为 init_check 模式
    let args: Vec<String> = env::args().collect();
    if args.len() > 1 && args[1] == "--init-check" {
        handle_init_check(&config);
        return;
    }

    // 监听并处理数据（循环监听）
    listen_loop(&config);
}

/// 处理 init_check 请求，写入 status.json
fn handle_init_check(config: &serde_json::Value) {
    let status = serde_json::json!({
        "status": "ok",
        "node_name": config["node_name"],
        "timestamp": Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
    });

    if let Ok(status_str) = serde_json::to_string_pretty(&status) {
        let _ = fs::write("status.json", &status_str);
        println!("{}", status_str);
    }

    // 同时写入标准的 output.json
    let output = serde_json::json!({
        "code": 0,
        "data": {
            "status": "ok",
            "node_name": config["node_name"]
        }
    });

    if let Ok(output_str) = serde_json::to_string(&output) {
        println!("{}", output_str);
    }
}

/// 检查并修复环境
fn check_and_fix_environment() -> bool {
    println!("Checking environment...");

    // 检查 Rust 工具链
    if !check_rust_installed() {
        eprintln!("Error: Rust is not installed. Please install Rust from https://rustup.rs/");
        return false;
    }

    // 检查 Cargo
    if !check_cargo_installed() {
        eprintln!("Error: Cargo is not installed.");
        return false;
    }

    // 检查编译产物
    let exe_name = if cfg!(target_os = "windows") {
        format!("{}.exe", "node_rust_grok_hands")
    } else {
        "node_rust_grok_hands".to_string()
    };

    let listener_exe_name = if cfg!(target_os = "windows") {
        format!("{}_listener.exe", "node_rust_grok_hands")
    } else {
        format!("{}_listener", "node_rust_grok_hands")
    };

    // 获取当前可执行文件所在目录
    let current_exe = env::current_exe().expect("Failed to get executable path");
    let node_dir = current_exe.parent().expect("Failed to get parent directory");

    let main_exe_path = node_dir.join(&exe_name);
    let listener_exe_path = node_dir.join(&listener_exe_name);

    // 检查主程序和监听器二进制文件是否存在
    let main_exists = main_exe_path.exists();
    let listener_exists = listener_exe_path.exists();

    if !main_exists || !listener_exists {
        if !main_exists {
            println!("Binary '{}' not found, building...", exe_name);
        }
        if !listener_exists {
            println!("Binary '{}' not found, building...", listener_exe_name);
        }
        if !build_project() {
            eprintln!("Build failed!");
            return false;
        }
    }

    println!("Environment check passed.");
    true
}

/// 检查 Rust 是否已安装
fn check_rust_installed() -> bool {
    Command::new("rustc")
        .arg("--version")
        .output()
        .is_ok()
}

/// 检查 Cargo 是否已安装
fn check_cargo_installed() -> bool {
    Command::new("cargo")
        .arg("--version")
        .output()
        .is_ok()
}

/// 构建项目
fn build_project() -> bool {
    println!("Building project in release mode...");

    // 获取当前可执行文件所在目录，即为项目根目录
    let current_exe = env::current_exe().expect("Failed to get executable path");
    let node_dir = current_exe.parent().expect("Failed to get parent directory");

    // 尝试从项目根目录查找 Cargo.toml
    let project_dir = node_dir
        .parent()
        .and_then(|p| p.parent())
        .unwrap_or(node_dir);

    println!("Building in: {:?}", project_dir);

    let status = Command::new("cargo")
        .args(&["build", "--release"])
        .current_dir(project_dir)
        .status();

    match status {
        Ok(status) => {
            if status.success() {
                println!("Build completed successfully.");
                true
            } else {
                eprintln!("Build failed with status: {:?}", status);
                false
            }
        }
        Err(e) => {
            eprintln!("Failed to execute cargo build: {}", e);
            false
        }
    }
}

/// 读取配置文件
fn read_config() -> serde_json::Value {
    // 获取当前可执行文件所在目录
    let exe_path = env::current_exe().expect("Failed to get executable path");
    let node_dir = exe_path.parent().expect("Failed to get parent directory");

    // 尝试在多个位置查找配置文件
    let config_paths = vec![
        node_dir.join("node_config.json"),
        node_dir.parent().unwrap_or(node_dir).join("node_config.json"),
        node_dir.parent().and_then(|p| p.parent()).unwrap_or(node_dir).join("node_config.json"),
    ];

    for config_path in &config_paths {
        if let Ok(config_str) = fs::read_to_string(config_path) {
            match serde_json::from_str(&config_str) {
                Ok(config) => return config,
                Err(e) => {
                    eprintln!("Failed to parse config at {:?}: {}", config_path, e);
                    continue;
                }
            }
        }
    }

    eprintln!("Failed to read config file from any of the expected locations");
    std::process::exit(1);
}

/// 循环监听并处理数据
fn listen_loop(config: &serde_json::Value) {
    let upper_file = config["listen_upper_file"]
        .as_str()
        .unwrap_or("../data/upper_data.json");

    let output_file = config["output_file"]
        .as_str()
        .unwrap_or("./output.json");

    let node_name = config["node_name"]
        .as_str()
        .unwrap_or("unknown");

    let process_flag = format!("_processed_{}", node_name);

    println!("Listening to: {}", upper_file);
    println!("Output to: {}", output_file);
    println!("Process flag: {}", process_flag);

    log_message(&format!("Node started: {}", node_name));
    log_message(&format!("Listening: {}", upper_file));

    loop {
        // 检查输入文件是否存在
        if !Path::new(upper_file).exists() {
            thread::sleep(Duration::from_millis(200));
            continue;
        }

        // 读取输入数据
        let data_str = match fs::read_to_string(upper_file) {
            Ok(s) => s,
            Err(e) => {
                log_message(&format!("Error reading input file: {}", e));
                thread::sleep(Duration::from_millis(200));
                continue;
            }
        };

        // 解析 JSON
        let mut data: serde_json::Value = match serde_json::from_str(&data_str) {
            Ok(d) => d,
            Err(e) => {
                log_message(&format!("JSON parse error: {}", e));
                thread::sleep(Duration::from_secs(1));
                continue;
            }
        };

        // 检查是否已处理
        if let Some(flag) = data.get(&process_flag) {
            if flag.as_bool().unwrap_or(false) {
                thread::sleep(Duration::from_millis(200));
                continue;
            }
        }

        // 应用过滤器
        if let Some(filter) = config.get("filter") {
            if !apply_filter(&data, filter) {
                thread::sleep(Duration::from_millis(200));
                continue;
            }
        }

        log_message("Processing data...");

        // 调用主程序处理
        let exe_name = if cfg!(target_os = "windows") {
            format!("{}.exe", "node_rust_grok_hands")
        } else {
            "node_rust_grok_hands".to_string()
        };

        // 获取当前可执行文件所在目录，以便找到主处理程序
        let current_exe = env::current_exe().expect("Failed to get executable path");
        let node_dir = current_exe.parent().expect("Failed to get parent directory");
        let main_exe_path = node_dir.join(&exe_name);

        let input_json = serde_json::to_string(&data).unwrap_or_else(|_| "{}".to_string());

        let output = Command::new(&main_exe_path)
            .arg(&input_json)
            .output();

        match output {
            Ok(out) => {
                if out.status.success() {
                    let result = String::from_utf8_lossy(&out.stdout);

                    // 写入输出文件
                    if let Err(e) = fs::write(output_file, result.as_ref()) {
                        log_message(&format!("Error writing output: {}", e));
                    } else {
                        log_message("Processing completed successfully");

                        // 标记为已处理
                        if let Some(obj) = data.as_object_mut() {
                            obj.insert(process_flag.clone(), serde_json::Value::Bool(true));
                        }

                        // 更新输入文件
                        if let Ok(updated_json) = serde_json::to_string_pretty(&data) {
                            let _ = fs::write(upper_file, updated_json);
                        }
                    }
                } else {
                    let error = String::from_utf8_lossy(&out.stderr);
                    log_message(&format!("Processing failed: {}", error));
                }
            }
            Err(e) => {
                log_message(&format!("Failed to execute {}: {}", exe_name, e));
            }
        }

        thread::sleep(Duration::from_millis(200));
    }
}

/// 应用过滤器
fn apply_filter(data: &serde_json::Value, filter: &serde_json::Value) -> bool {
    if let Some(obj) = filter.as_object() {
        for (key, value) in obj {
            if let Some(data_value) = data.get(key) {
                if data_value != value {
                    return false;
                }
            } else {
                return false;
            }
        }
    }
    true
}

/// 记录日志
fn log_message(message: &str) {
    let timestamp = Local::now().format("%Y-%m-%d %H:%M:%S");
    let log_line = format!("[{}] {}", timestamp, message);
    println!("{}", log_line);

    // 写入日志文件
    let log_dir = "logs";
    if !Path::new(log_dir).exists() {
        let _ = fs::create_dir_all(log_dir);
    }

    let log_file = Path::new(log_dir).join("listener.log");
    if let Ok(mut file) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_file)
    {
        let _ = writeln!(file, "{}", log_line);
    }
}
