# Stage 8 构建版本解析

## Resolver 行为

1. 读取 `CC_SWITCH_CHANNEL` 和 `CC_SWITCH_VERSION`；默认 `stable/latest`；
2. 请求上游 release metadata，拒绝 draft、prerelease、缺少 semver tag 或无匹配 Linux `amd64/arm64` 资产的 release；
3. 按明确资产规则选择 musl/glibc、架构和格式，校验下载大小、checksum（优先上游 checksum/signature）；
4. 生成 `ResolvedRelease` JSON 和构建 manifest；
5. Docker build 使用 resolver 输出的 `CC_SWITCH_VERSION`、URL、SHA-256 和 asset name；
6. 镜像写入 OCI labels：`org.aisc.cc-switch.version`、`org.aisc.cc-switch.commit`、`org.aisc.cc-switch.asset-sha256`、`org.aisc.build-manifest`。

## 接口与回滚

- `aisc build --cc-switch-version latest|vX.Y.Z --cc-switch-channel stable`；
- 本地 `latest` 可使用带 TTL 的 metadata/cache，但产物必须显示解析结果；
- CI 先解析并上传 manifest，再用 manifest 构建；发布重新校验 checksum；
- 上游不可达时，只有提供完整的显式版本 manifest 才允许离线构建；不得默默使用 `versions.env` 中旧固定值；
- 回滚只需传入先前 manifest 的精确版本和 checksum。

## 测试

- fake release API：latest、prerelease、draft、分页、限流、无资产、架构 fallback；
- checksum mismatch、下载超时、代理 fallback 和离线显式版本；
- Docker build args/labels 与 manifest 一致；
- `versions.env` 向后兼容但不再是 latest 的唯一事实源。
