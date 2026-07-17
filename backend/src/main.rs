use std::fs;
use std::fs::OpenOptions;
use std::io::{self, Write};
use std::net::{IpAddr, SocketAddr};
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use caps::{CapSet, Capability};
use serde::Deserialize;
use tokio::io::AsyncReadExt;
use tokio::process::{Child, Command as TokioCommand};
use tokio::sync::RwLock;
use tokio::time::sleep;
use tonic::{transport::Server, Request, Response, Status};

pub mod multiverse {
    tonic::include_proto!("multiverse");
}

use multiverse::multiverse_server::{Multiverse, MultiverseServer};
use multiverse::{
    ActiLineRequest, CommandReply, Empty, PcapFileReply, PcapNameRequest, PowerRequest,
    WakeUpRequest,
};

const PCU: &str = "pcu_state.txt";
const WAKEUPLINE: &str = "wakeup_state.txt";
const ACT: &str = "acti_state.txt";
const PCAP: &str = "pcap_state.txt";
const LOG_FILE: &str = "command_log.txt";

const DEFAULT_PCAP_NAME: &str = "capture.pcap";
const CONFIG_FILE: &str = "config.json";

#[derive(Clone, Deserialize)]
struct AppConfig {
    listener: ListenerConfig,
    pcap_parameters: CaptureParameters,
}

#[derive(Clone, Deserialize)]
struct ListenerConfig {
    ethernet: NetworkInterfaceConfig,
    wifi: NetworkInterfaceConfig,
}

#[derive(Clone, Deserialize)]
struct NetworkInterfaceConfig {
    enabled: bool,
    priority: u8,
    ip: String,
    port: u16,
}

impl ListenerConfig {
    fn active(&self) -> Result<&NetworkInterfaceConfig, String> {
        [&self.ethernet, &self.wifi]
            .into_iter()
            .filter(|listener| listener.enabled)
            .min_by_key(|listener| listener.priority)
            .ok_or_else(|| "au moins ethernet ou wifi doit etre active".to_string())
    }
}

#[derive(Clone, Deserialize)]
struct CaptureParameters {
    if_name: String,
    size_mb: u32,
    slices: u8,
}

fn config_path() -> Result<PathBuf, String> {
    let local = PathBuf::from(CONFIG_FILE);
    if local.is_file() {
        return Ok(local);
    }

    let parent = PathBuf::from("..").join(CONFIG_FILE);
    if parent.is_file() {
        return Ok(parent);
    }

    Err(format!("{} introuvable", CONFIG_FILE))
}

fn load_config() -> Result<AppConfig, String> {
    let path = config_path()?;
    let content = fs::read_to_string(&path)
        .map_err(|err| format!("lecture de {} impossible: {}", path.display(), err))?;
    let config: AppConfig = serde_json::from_str(&content)
        .map_err(|err| format!("JSON invalide dans {}: {}", path.display(), err))?;

    let listener = config.listener.active()?;
    if listener.ip.parse::<IpAddr>().is_err() {
        return Err(format!("listener IP invalide: {}", listener.ip));
    }
    if config.pcap_parameters.if_name.trim().is_empty() {
        return Err("pcap_parameters.if_name ne peut pas etre vide".to_string());
    }
    if config.pcap_parameters.size_mb == 0 {
        return Err("pcap_parameters.size_mb doit etre superieur a 0".to_string());
    }
    if !(1..=5).contains(&config.pcap_parameters.slices) {
        return Err("pcap_parameters.slices doit etre compris entre 1 et 5".to_string());
    }

    Ok(config)
}

fn write_state(path: &str, state: &str) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create(true).open(path)?;
    write!(file, "- State: {}\n", state)?;
    file.flush()
}

fn append_log(entry: &str) -> io::Result<()> {
    let mut file = OpenOptions::new()
        .append(true)
        .create(true)
        .open(LOG_FILE)?;
    writeln!(file, "{}", entry)
}

fn reply_from(res: io::Result<()>, msg: &str) -> CommandReply {
    match res {
        Ok(_) => CommandReply {
            ok: true,
            message: format!("OK {}", msg),
        },
        Err(e) => CommandReply {
            ok: false,
            message: format!("ERR {}: {}", msg, e),
        },
    }
}

fn log_and_return(entry: String, reply: CommandReply) -> CommandReply {
    let log_line = format!("{} -> {}", entry, reply.message);
    let _ = append_log(&log_line);
    println!("{}", log_line);
    reply
}

struct AppState {
    pcap_child: Arc<RwLock<Option<Child>>>,
    pcap_name: Arc<RwLock<String>>,
    pcap_name_set: Arc<RwLock<bool>>,
    capture: CaptureParameters,
}

impl AppState {
    fn new(capture: CaptureParameters) -> Self {
        AppState {
            pcap_child: Arc::new(RwLock::new(None)),
            pcap_name: Arc::new(RwLock::new(DEFAULT_PCAP_NAME.to_string())),
            pcap_name_set: Arc::new(RwLock::new(false)),
            capture,
        }
    }
}

fn enable_net_raw() -> io::Result<()> {
    caps::raise(None, CapSet::Inheritable, Capability::CAP_NET_RAW)
        .map_err(|e| io::Error::new(io::ErrorKind::Other, e))?;

    unsafe {
        if libc::prctl(
            libc::PR_CAP_AMBIENT,
            libc::PR_CAP_AMBIENT_RAISE,
            Capability::CAP_NET_RAW as libc::c_ulong,
            0,
            0,
        ) != 0
        {
            return Err(io::Error::last_os_error());
        }
    }

    Ok(())
}

async fn start_pcap(state: &Arc<AppState>) -> CommandReply {
    let mut child_guard = state.pcap_child.write().await;
    if child_guard.is_some() {
        return CommandReply {
            ok: false,
            message: "ERR PCAP START: capture deja en cours".to_string(),
        };
    }

    if !*state.pcap_name_set.read().await {
        return CommandReply {
            ok: false,
            message: "ERR PCAP START: nom de fichier non defini, utiliser PcapSetName d'abord"
                .to_string(),
        };
    }

    let filename = state.pcap_name.read().await.clone();
    if let Err(e) = enable_net_raw() {
        return CommandReply {
            ok: false,
            message: format!("ERR PCAP START: impossible d'activer CAP_NET_RAW: {}", e),
        };
    }

    let mut child = match TokioCommand::new("tcpdump")
        .args([
            "-i",
            &state.capture.if_name,
            "-w",
            &filename,
            "-C",
            &state.capture.size_mb.to_string(),
            "-W",
            &state.capture.slices.to_string(),
            "-U",
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            return CommandReply {
                ok: false,
                message: format!("ERR PCAP START: impossible de lancer tcpdump: {}", e),
            }
        }
    };

    sleep(Duration::from_millis(300)).await;

    match child.try_wait() {
        Ok(Some(status)) => {
            let mut stderr_output = String::new();
            if let Some(mut stderr) = child.stderr.take() {
                let _ = stderr.read_to_string(&mut stderr_output).await;
            }
            CommandReply {
                ok: false,
                message: format!(
                    "ERR PCAP START: tcpdump a quitte immediatement ({}): {}",
                    status,
                    stderr_output.trim()
                ),
            }
        }
        Ok(None) => {
            *child_guard = Some(child);
            let _ = write_state(PCAP, "START");
            CommandReply {
                ok: true,
                message: format!("OK PCAP START {}", filename),
            }
        }
        Err(e) => CommandReply {
            ok: false,
            message: format!("ERR PCAP START: erreur verification processus: {}", e),
        },
    }
}

async fn stop_pcap(state: &Arc<AppState>) -> CommandReply {
    let mut child_guard = state.pcap_child.write().await;
    match child_guard.take() {
        Some(mut child) => {
            let _ = child.kill().await;
            let _ = child.wait().await;
            let _ = write_state(PCAP, "STOP");
            *state.pcap_name_set.write().await = false;
            CommandReply {
                ok: true,
                message: "OK PCAP STOP".to_string(),
            }
        }
        None => CommandReply {
            ok: false,
            message: "ERR PCAP STOP: aucune capture en cours".to_string(),
        },
    }
}

async fn set_pcap_name(state: &Arc<AppState>, name: &str) -> CommandReply {
    if name.is_empty() {
        return CommandReply {
            ok: false,
            message: "ERR PCAP NAME: nom de fichier manquant".to_string(),
        };
    }

    let filename = if name.ends_with(".pcap") {
        name.to_string()
    } else {
        format!("{}.pcap", name)
    };

    {
        let mut child_guard = state.pcap_child.write().await;
        if let Some(mut child) = child_guard.take() {
            let _ = child.kill().await;
            let _ = child.wait().await;
            let _ = write_state(PCAP, "STOP");
        }
    }

    *state.pcap_name.write().await = filename.clone();
    *state.pcap_name_set.write().await = true;
    let _ = write_state(PCAP, "NAME");
    CommandReply {
        ok: true,
        message: format!("OK PCAP NAME {}", filename),
    }
}

async fn delete_pcap(state: &Arc<AppState>, name: &str) -> CommandReply {
    if name.is_empty() {
        return CommandReply {
            ok: false,
            message: "ERR PCAP DELETE: nom de fichier manquant".to_string(),
        };
    }

    let filename = if name.ends_with(".pcap") {
        name.to_string()
    } else {
        format!("{}.pcap", name)
    };

    match fs::remove_file(&filename) {
        Ok(_) => {
            *state.pcap_name.write().await = DEFAULT_PCAP_NAME.to_string();
            *state.pcap_name_set.write().await = false;
            let _ = write_state(PCAP, "STOP");
            CommandReply {
                ok: true,
                message: format!("OK PCAP DELETE {}", filename),
            }
        }
        Err(err) if err.kind() == io::ErrorKind::NotFound => {
            *state.pcap_name.write().await = DEFAULT_PCAP_NAME.to_string();
            *state.pcap_name_set.write().await = false;
            let _ = write_state(PCAP, "STOP");
            CommandReply {
                ok: true,
                message: format!("OK PCAP DELETE {} (already absent)", filename),
            }
        }
        Err(err) => CommandReply {
            ok: false,
            message: format!(
                "ERR PCAP DELETE: impossible de supprimer {}: {}",
                filename, err
            ),
        },
    }
}

/// `tcpdump -C ... -W ...` writes rotated captures as `<name>0`,
/// `<name>1`, and so on.  Prefer an exact file name, but otherwise return
/// the most recently modified rotated file for the configured capture name.
async fn resolve_pcap_file(state: &Arc<AppState>, requested_name: &str) -> Result<PathBuf, Status> {
    let configured_name = state.pcap_name.read().await.clone();
    if requested_name != configured_name {
        return Err(Status::not_found(format!(
            "PCAP GET: {} is not the configured capture file",
            requested_name
        )));
    }

    let exact_path = PathBuf::from(&configured_name);
    if exact_path.is_file() {
        return Ok(exact_path);
    }

    let mut newest: Option<(std::time::SystemTime, PathBuf)> = None;
    for slice in 0..state.capture.slices {
        let candidate = PathBuf::from(format!("{}{}", configured_name, slice));
        let modified = match fs::metadata(&candidate).and_then(|metadata| metadata.modified()) {
            Ok(modified) => modified,
            Err(_) => continue,
        };

        if newest
            .as_ref()
            .map_or(true, |(latest, _)| modified > *latest)
        {
            newest = Some((modified, candidate));
        }
    }

    newest.map(|(_, path)| path).ok_or_else(|| {
        Status::not_found(format!(
            "PCAP GET: could not find {} or any rotated capture files",
            configured_name
        ))
    })
}

pub struct MultiverseService {
    state: Arc<AppState>,
}

#[tonic::async_trait]
impl Multiverse for MultiverseService {
    async fn pcap_get(
        &self,
        request: Request<PcapNameRequest>,
    ) -> Result<Response<PcapFileReply>, Status> {
        let name = request.into_inner().name;
        let path = resolve_pcap_file(&self.state, name.trim()).await?;
        let content = fs::read(&path).map_err(|e| {
            Status::internal(format!(
                "PCAP GET: could not read {}: {}",
                path.display(),
                e
            ))
        })?;

        Ok(Response::new(PcapFileReply {
            filename: path.to_string_lossy().into_owned(),
            content,
        }))
    }

    async fn set_power(
        &self,
        request: Request<PowerRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let on = request.into_inner().on;
        let label = if on { "1" } else { "0" };
        let res = write_state(PCU, if on { "ON" } else { "OFF" });
        let reply = reply_from(res, &format!("POWER {}", label));
        Ok(Response::new(log_and_return(
            format!("POWER {}", label),
            reply,
        )))
    }

    async fn set_wake_up(
        &self,
        request: Request<WakeUpRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let on = request.into_inner().on;
        let label = if on { "1" } else { "0" };
        let res = write_state(WAKEUPLINE, if on { "ON" } else { "OFF" });
        let reply = reply_from(res, &format!("WAKE-UP {}", label));
        Ok(Response::new(log_and_return(
            format!("WAKE-UP {}", label),
            reply,
        )))
    }

    async fn set_acti_line(
        &self,
        request: Request<ActiLineRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let on = request.into_inner().on;
        let label = if on { "1" } else { "0" };
        let res = write_state(ACT, if on { "ON" } else { "OFF" });
        let reply = reply_from(res, &format!("ACTI-LINE {}", label));
        Ok(Response::new(log_and_return(
            format!("ACTI-LINE {}", label),
            reply,
        )))
    }

    async fn pcap_start(&self, _request: Request<Empty>) -> Result<Response<CommandReply>, Status> {
        let reply = start_pcap(&self.state).await;
        Ok(Response::new(log_and_return(
            "PCAP START".to_string(),
            reply,
        )))
    }

    async fn pcap_stop(&self, _request: Request<Empty>) -> Result<Response<CommandReply>, Status> {
        let reply = stop_pcap(&self.state).await;
        Ok(Response::new(log_and_return(
            "PCAP STOP".to_string(),
            reply,
        )))
    }

    async fn pcap_set_name(
        &self,
        request: Request<PcapNameRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let name = request.into_inner().name;
        let reply = set_pcap_name(&self.state, name.trim()).await;
        Ok(Response::new(log_and_return(
            format!("PCAP NAME {}", name),
            reply,
        )))
    }

    async fn pcap_delete(
        &self,
        request: Request<PcapNameRequest>,
    ) -> Result<Response<CommandReply>, Status> {
        let name = request.into_inner().name;
        let reply = delete_pcap(&self.state, name.trim()).await;
        Ok(Response::new(log_and_return(
            format!("PCAP DELETE {}", name),
            reply,
        )))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config =
        load_config().map_err(|err| std::io::Error::new(std::io::ErrorKind::InvalidInput, err))?;
    let listener = config
        .listener
        .active()
        .expect("validated enabled listener");
    let ip = listener
        .ip
        .parse::<IpAddr>()
        .expect("validated listener IP");
    let addr = SocketAddr::new(ip, listener.port);
    let state = Arc::new(AppState::new(config.pcap_parameters));
    let service = MultiverseService { state };

    println!("Backend gRPC en ecoute sur {}", addr);
    println!(
        "Reseau: ethernet enabled={} priority={}, wifi enabled={} priority={}",
        config.listener.ethernet.enabled,
        config.listener.ethernet.priority,
        config.listener.wifi.enabled,
        config.listener.wifi.priority,
    );

    Server::builder()
        .add_service(MultiverseServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}
