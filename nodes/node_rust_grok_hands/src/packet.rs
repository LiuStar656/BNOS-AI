use serde::{Deserialize, Serialize};

/// 输出数据包结构
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutputPacket {
    pub code: i32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl OutputPacket {
    /// 创建成功响应
    pub fn success(data: Option<serde_json::Value>) -> Self {
        Self {
            code: 0,
            data,
            error: None,
        }
    }

    /// 创建错误响应
    pub fn error(msg: &str) -> Self {
        Self {
            code: -1,
            data: None,
            error: Some(msg.to_string()),
        }
    }
}
