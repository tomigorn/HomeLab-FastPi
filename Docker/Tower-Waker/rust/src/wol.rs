//! Wake-on-LAN magic packet (same file in Beefy-Waker and Tower-Waker).

use std::net::{Ipv4Addr, UdpSocket};

const WAKE_UDP_PORT: u16 = 9;

/// `bytes.fromhex(mac.replace(":", "").replace("-", ""))`, exactly 6 bytes.
pub fn parse_mac(mac: &str) -> Option<[u8; 6]> {
    let hex: String = mac.chars().filter(|&c| c != ':' && c != '-').collect();
    let mut out = Vec::with_capacity(6);
    let mut chars = hex.chars().peekable();
    loop {
        while chars.peek().is_some_and(|c| c.is_ascii_whitespace()) {
            chars.next();
        }
        let Some(h) = chars.next() else { break };
        let l = chars.next()?;
        out.push((h.to_digit(16)? * 16 + l.to_digit(16)?) as u8);
    }
    out.try_into().ok()
}

pub fn magic_packet(mac: &[u8; 6]) -> Vec<u8> {
    let mut p = vec![0xff; 6];
    for _ in 0..16 {
        p.extend_from_slice(mac);
    }
    p
}

/// One packet to `broadcast`:9. Only IPv4 literals are accepted (no DNS lookups).
pub fn send(mac: &[u8; 6], broadcast: &str) -> std::io::Result<()> {
    let ip: Ipv4Addr = broadcast
        .parse()
        .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidInput, format!("not an IPv4 address: {broadcast:?}")))?;
    let s = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0))?;
    s.set_broadcast(true)?;
    s.send_to(&magic_packet(mac), (ip, WAKE_UDP_PORT))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mac_formats() {
        assert_eq!(parse_mac("02:00:5e:10:20:30"), Some([2, 0, 0x5e, 0x10, 0x20, 0x30]));
        assert_eq!(parse_mac("02-00-5E-10-20-30"), Some([2, 0, 0x5e, 0x10, 0x20, 0x30]));
        assert_eq!(parse_mac("02005e102030"), Some([2, 0, 0x5e, 0x10, 0x20, 0x30]));
        assert_eq!(parse_mac("02:00:5e:10:20"), None);
        assert_eq!(parse_mac("02:00:5e:10:20:3"), None);
        assert_eq!(parse_mac("zz:00:5e:10:20:30"), None);
        assert_eq!(parse_mac(""), None);
    }

    #[test]
    fn packet_layout() {
        let p = magic_packet(&[1, 2, 3, 4, 5, 6]);
        assert_eq!(p.len(), 102);
        assert_eq!(&p[..6], &[0xff; 6]);
        assert_eq!(&p[96..], &[1, 2, 3, 4, 5, 6]);
    }

    #[test]
    fn hostnames_are_refused() {
        assert!(send(&[0; 6], "256.1.1.1").is_err());
        assert!(send(&[0; 6], "localhost").is_err());
    }
}
