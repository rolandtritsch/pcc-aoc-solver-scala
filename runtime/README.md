# Dedicated AoC runtime

The company runs through Paperclip's SSH environment driver on a dedicated
Fargate service. Its image supplies Java, sbt, OpenCode, Git, GitHub CLI, Python,
and the company helpers. `toolchain.json` pins Java/sbt downloads and checksums
and the OpenCode version. The Docker base is pinned by digest. This image
currently supports Linux x86_64.

The controller's existing solution checkout remains the source Paperclip stages
and restores. Tool binaries live under `/opt` in the image. Separate runtime EFS
holds staged workspaces, dependency caches, and the SSH host key. The runtime
cannot mount the controller's volume or use its AWS role.

## Build and deploy

In `pulumi-paperclip`, configure `aoc_runtime_enabled=true` and
`aoc_runtime_ssh_public_key` with the controller's generated Ed25519 public key.
Run `pulumi up` to create the ECR repository. Keep the private key outside Git.

Publish from this repository:

```bash
python3 runtime/publish.py --repository <aocRuntimeRepository-stack-output>
```

Set Pulumi's `aoc_runtime_image` to the printed `repository@sha256:...` reference,
preview the update, then deploy it. The service uses 2 vCPU and 8 GiB of memory.
Only the Paperclip service's security group can connect to SSH. Runtime IAM
permits ECS Exec management, without application or infrastructure credentials.

Read `/workspaces/.ssh-host/ssh_host_ed25519_key.pub` using ECS Exec on the new
runtime task. Write a known-hosts file containing the stack's `aocRuntimeHost`
followed by the public key's algorithm and base64 data. This pins the host identity
without trusting an unauthenticated network scan. Host keys persist on runtime
EFS, so task replacement preserves the identity.

With all company agents paused, bind the environment:

```bash
python3 runtime/configure-company.py --company-id <company-id> \
  --host <aocRuntimeHost-stack-output> \
  --private-key-file <private-key-path> --known-hosts-file <known-hosts-path>
```

The script reads the existing Paperclip CLI login, stores the SSH private key in
the Paperclip-encrypted vault, probes the environment, and assigns all seven
agents using configuration revision checks. It preserves secret bindings and
keeps agents paused. Afterward the vault owns the client key; retain an encrypted
backup or remove the temporary local copy.

The company remains on the legacy OpenCode runner because its CTO and WatchDog
use custom launchers. Those wrappers select the staged repository dynamically,
keep Paperclip's credential-broker PATH, and configure the known solution origin
for explicit company publication. Set `AOC_PAPERCLIP_API_URL` to the controller's
public URL so remote helpers can reach the API.

## Verify and update

Verify the environment probe, authenticated GitHub access, and Java/OpenCode
versions. In the staged template run:

```bash
sbt --batch 'clean; compile; testOnly *; scalafmtCheckAll; scalafmtSbtCheck; run'
```

Inspect the actual test count. For a runtime update, change the version pins or
company helpers, rebuild, publish, and update the image digest in Pulumi. Check
the ECS rollout and environment probe before resuming authorized company work.
Credentials stay in runtime secret bindings and never enter the image.

To roll back, restore the previous image digest and redeploy. Do not delete the
runtime EFS volume while it contains un-restored work. The old shared Java/sbt
toolchain has already been removed from the controller EFS; this runtime no
longer depends on it.
