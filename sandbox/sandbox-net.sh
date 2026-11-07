#!/bin/bash
# 沙箱出口规则（2026-11-04 用户定：能上网，但宿主机和局域网挡死）
# 关键：WSL 的 DNS 在 10.255.255.254（10/8 网段内），必须先放行，否则一断网就全断
GW=$(ip route | awk '/default/{print $3; exit}')
iptables -F SANDBOX_OUT 2>/dev/null || iptables -N SANDBOX_OUT
iptables -F SANDBOX_OUT

# 1) 放行 DNS：resolv.conf 里的 nameserver + 网关
for ns in $(awk '/^nameserver/{print $2}' /etc/resolv.conf) $GW; do
  [ -n "$ns" ] || continue
  iptables -A SANDBOX_OUT -d "$ns" -p udp --dport 53 -j ACCEPT
  iptables -A SANDBOX_OUT -d "$ns" -p tcp --dport 53 -j ACCEPT
done

# 2) 私有网段一律拒绝（宿主机 = 网关 IP，也在这几个段里；除 53 外全挡）
iptables -A SANDBOX_OUT -d 10.0.0.0/8     -j REJECT
iptables -A SANDBOX_OUT -d 172.16.0.0/12  -j REJECT
iptables -A SANDBOX_OUT -d 192.168.0.0/16 -j REJECT
iptables -A SANDBOX_OUT -d 169.254.0.0/16 -j REJECT

iptables -D OUTPUT -j SANDBOX_OUT 2>/dev/null || true
iptables -I OUTPUT 1 -j SANDBOX_OUT

if command -v ip6tables >/dev/null 2>&1; then
  ip6tables -D OUTPUT -j SANDBOX_OUT6 2>/dev/null || true
  ip6tables -F SANDBOX_OUT6 2>/dev/null || ip6tables -N SANDBOX_OUT6
  ip6tables -A SANDBOX_OUT6 -d fe80::/10 -j REJECT
  ip6tables -A SANDBOX_OUT6 -d fc00::/7  -j REJECT
  ip6tables -I OUTPUT 1 -j SANDBOX_OUT6
fi
echo "[sandbox-net] 已加载 网关=$GW DNS=$(awk '/^nameserver/{print $2}' /etc/resolv.conf | tr '\n' ' ')"
