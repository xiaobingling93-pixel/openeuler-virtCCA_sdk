// Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

//! KDC Agent binary entry point.

fn main() {
    if let Err(e) = kdc_agent::init() {
        eprintln!("kdc_agent init failed: {}", e);
        std::process::exit(1);
    }
    if let Err(e) = kdc_agent::start() {
        eprintln!("kdc_agent start failed: {}", e);
        std::process::exit(1);
    }
    if let Err(e) = kdc_agent::stop() {
        eprintln!("kdc_agent stop failed: {}", e);
        std::process::exit(1);
    }
}
