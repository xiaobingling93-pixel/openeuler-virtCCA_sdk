// Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

//! KDC Agent library for KunPeng Data Controller.
//!
//! Provides a plugin-based agent framework with TLS HTTP server,
//! PSK-based encryption, and dynamic plugin lifecycle management.
#![cfg_attr(coverage_nightly, feature(coverage_attribute))]

pub mod config_manager;
pub mod db_manager;
pub mod handler_registry;
pub mod http_server;
pub mod logger;
pub mod plugin_manager;
pub mod process_manager;
pub mod psk_manager;
pub mod token_verifier;
pub mod types;

pub use process_manager::{init, start, stop};
