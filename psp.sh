#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

host_os="$(uname -s)"

# PSPSDK's tools are installed in $PSPDEV/bin. Make the common setup work even
# when PSPDEV is exported but its bin directory was not added to PATH.
if [[ -n "${PSPDEV:-}" && -d "${PSPDEV}/bin" ]]; then
    case ":${PATH}:" in
        *":${PSPDEV}/bin:"*) ;;
        *) export PATH="${PSPDEV}/bin:${PATH}" ;;
    esac
fi

# macOS ships GNU Make 3.81 as `make`, which is too old for this Makefile.
# Homebrew installs a current GNU Make as `gmake`.
if [[ -n "${MAKE:-}" ]]; then
    make_cmd="$MAKE"
elif [[ "$host_os" == "Darwin" ]]; then
    make_cmd="gmake"
else
    make_cmd="make"
fi

if ! command -v "$make_cmd" >/dev/null 2>&1; then
    if [[ "$host_os" == "Darwin" && "$make_cmd" == "gmake" ]]; then
        echo "error: GNU Make is required; install it with 'brew install make'" >&2
    else
        echo "error: unable to find build tool: $make_cmd" >&2
    fi
    exit 1
fi

for tool in psp-config psp-gcc; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "error: unable to find $tool; install PSPSDK and add \$PSPDEV/bin to PATH" >&2
        exit 1
    fi
done

if [[ ! -f Makefile ]]; then
    echo "error: Makefile not found in $repo_root" >&2
    exit 1
fi

if [[ -n "${JOBS:-}" ]]; then
    jobs="$JOBS"
elif command -v nproc >/dev/null 2>&1; then
    jobs="$(nproc)"
else
    jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
fi

echo "Building MM psp-port with $jobs job(s) using $make_cmd..."
exec "$make_cmd" -j"$jobs" psp-port "$@"
