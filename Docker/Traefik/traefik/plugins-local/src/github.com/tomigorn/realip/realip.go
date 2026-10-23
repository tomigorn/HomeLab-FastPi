// Package realip sets X-Forwarded-For and X-Real-Ip to exactly one address: the real client.
package realip

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"strings"
)

// Config lists the connection addresses (the Cloudflare tunnel) whose Cf-Connecting-Ip is believed.
type Config struct {
	TrustedIPs []string `json:"trustedIPs,omitempty"`
}

// CreateConfig returns the default configuration.
func CreateConfig() *Config {
	return &Config{}
}

// RealIP is the middleware.
type RealIP struct {
	next    http.Handler
	trusted []*net.IPNet
}

// New builds the middleware.
func New(_ context.Context, next http.Handler, config *Config, _ string) (http.Handler, error) {
	nets := make([]*net.IPNet, 0, len(config.TrustedIPs))
	for _, entry := range config.TrustedIPs {
		cidr := strings.TrimSpace(entry)
		if !strings.Contains(cidr, "/") {
			if strings.Contains(cidr, ":") {
				cidr += "/128"
			} else {
				cidr += "/32"
			}
		}
		_, ipNet, err := net.ParseCIDR(cidr)
		if err != nil {
			return nil, fmt.Errorf("realip: invalid trustedIPs entry %q: %w", entry, err)
		}
		nets = append(nets, ipNet)
	}
	return &RealIP{next: next, trusted: nets}, nil
}

func (r *RealIP) isTrusted(ip net.IP) bool {
	for _, ipNet := range r.trusted {
		if ipNet.Contains(ip) {
			return true
		}
	}
	return false
}

func parseIP(value string) net.IP {
	return net.ParseIP(strings.TrimSpace(value))
}

func (r *RealIP) ServeHTTP(rw http.ResponseWriter, req *http.Request) {
	host, _, err := net.SplitHostPort(req.RemoteAddr)
	if err != nil {
		host = req.RemoteAddr
	}
	client := parseIP(host)
	if client != nil && r.isTrusted(client) {
		if forwarded := parseIP(req.Header.Get("Cf-Connecting-Ip")); forwarded != nil {
			client = forwarded
		}
	}
	if client == nil {
		req.Header.Del("X-Forwarded-For")
		req.Header.Del("X-Real-Ip")
	} else {
		req.Header.Set("X-Forwarded-For", client.String())
		req.Header.Set("X-Real-Ip", client.String())
	}
	r.next.ServeHTTP(rw, req)
}
