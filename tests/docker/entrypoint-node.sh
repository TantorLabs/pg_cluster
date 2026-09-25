#!/bin/bash
# Entrypoint for pg-node containers
#
# Prepares the kernel module directory structure so that
# community.general.modprobe doesn't fail on missing modules.builtin.
# Also creates a dummy /dev/watchdog device for the patroni role.
set -e

KERNEL_VER="$(uname -r)"
MODDIR="/lib/modules/${KERNEL_VER}"

# Create modules.builtin listing softdog as built-in so the
# community.general.modprobe module considers it already loaded.
mkdir -p "$MODDIR/kernel/drivers/watchdog"
if [ ! -f "$MODDIR/modules.builtin" ]; then
    echo "kernel/drivers/watchdog/softdog.ko" > "$MODDIR/modules.builtin"
fi
if [ ! -f "$MODDIR/modules.dep" ]; then
    echo "kernel/drivers/watchdog/softdog.ko:" > "$MODDIR/modules.dep"
fi

# Create dummy /dev/watchdog if it doesn't exist (patroni role chowns it)
if [ ! -e /dev/watchdog ]; then
    mknod /dev/watchdog c 10 130 2>/dev/null || true
fi

# Replace modprobe with a wrapper that succeeds for softdog (no kernel
# module access in containers). The original is preserved as modprobe.real.
if [ -x /usr/sbin/modprobe ] && [ ! -e /usr/sbin/modprobe.real ]; then
    mv /usr/sbin/modprobe /usr/sbin/modprobe.real
fi
cat > /usr/sbin/modprobe <<'WRAPPER'
#!/bin/bash
# Fake modprobe for Docker testing — always succeeds
exit 0
WRAPPER
chmod +x /usr/sbin/modprobe

exec /lib/systemd/systemd
