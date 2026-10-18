# 第三方来源与许可证

VexBot 自有代码采用 `AGPL-3.0-or-later`，见 [LICENSE](https://github.com/AlancoSage/StarBridge/blob/main/LICENSE)。源码根目录、新构建游戏端 JAR 的 `META-INF/licenses/VexBot/` 和官网 ZIP 中提供 `LICENSE`；新构建的 Bot ZIP 提供 `docs/LICENSE.md`。历史 JAR 保留原许可目录。本文件记录第三方文件和依赖的原始许可证；这些许可证继续适用于相应第三方材料。

## 仓库包含的 Gradle Wrapper

以下目录中的 `gradlew`、`gradlew.bat`、`gradle/wrapper/gradle-wrapper.jar` 来源于 Gradle，采用 **Apache-2.0**：

- `bridge-forge/`
- `bridge-forge-1.18.2/`
- `bridge-forge-1.19.2/`
- `bridge-neoforge/`

保留启动脚本中原有的版权与许可注释：`Copyright © 2015-2021 the original authors.`（POSIX）及 `Copyright 2015 the original author or authors.`（Windows）。Wrapper 的原作者许可见 [GradleWrapperMain.java](https://github.com/gradle/gradle/blob/v8.1.1/subprojects/wrapper/src/main/java/org/gradle/wrapper/GradleWrapperMain.java)，其中版权声明为 `Copyright 2007 the original author or authors.`。Apache-2.0 许可全文附于本文末尾。

四个 Wrapper JAR 的 SHA-256 均为 `ed2c26eba7cfb93cc2b7785d05e534f07b5b48b5e7fc941921cd098628abca58`，匹配 [Gradle 官方 8.1 / 8.1.1 Wrapper 校验值](https://gradle.org/release-checksums/)。各 `gradle-wrapper.properties` 指定下载 Gradle 8.8；下载的 Gradle 发行版和其第三方依赖仍适用发行版自带的许可文件。

## Bukkit 插件包含的 Gson

- 组件：Google Gson **2.13.2**，**Apache-2.0**。
- 原作者声明：`Copyright (C) 2008 Google Inc.`。
- 来源：[Gson 2.13.2 LICENSE](https://github.com/google/gson/blob/gson-parent-2.13.2/LICENSE)。
- 构建声明：`bridge/pom.xml` 与 `bridge/build.ps1`。
- 打包位置：当前构建的 `VexBot-0.5.4.jar` 及其 `StarBridge-0.5.4.jar` 兼容副本中的 `cn/starbridge/lib/gson/`；历史 JAR 名称按对应版本保留。
- 修改说明：构建时将 `com.google.gson` 包名和对应类引用重定位为 `cn.starbridge.lib.gson`。
- 随 JAR 保留的许可：`META-INF/licenses/Gson-LICENSE.txt`；对应仓库文件为 [Gson-LICENSE.txt](https://github.com/AlancoSage/StarBridge/blob/main/bridge/src/main/resources/META-INF/licenses/Gson-LICENSE.txt)。

## Fabric 游戏端的 Yarn 映射

`bridge-fabric/build.py` 从 FabricMC Yarn 读取 Tiny v2 映射，生成 Fabric JAR 内的 `starbridge-fabric-mappings.json`。以下 Minecraft 版本使用 Yarn：`1.16.5+build.10`、`1.18.2+build.4`、`1.19.2+build.28`、`1.20.1+build.10`、`1.21.1+build.3`、`1.21.8+build.1`、`1.21.11+build.6`。

这些映射来源于 FabricMC Yarn contributors，采用 **CC0-1.0**，见 [Yarn LICENSE](https://github.com/FabricMC/yarn/blob/1.21.8/LICENSE)。映射数据继续适用 CC0；VexBot 的解析和适配代码适用项目许可证。

`bridge-fabric/bindings/` 与 `bridge-neoforge/bindings/` 是适配器声明的 API 名称与描述符。构建器核对官方游戏类声明，仅输出适配器所声明的接口表面；构建使用的 Minecraft 服务端 JAR、游戏类和完整官方映射文件均不包含在项目分发包中。

## 安装时获取的 Python 依赖

`requirements.lock.txt` 固定以下版本。依赖由安装器从 PyPI 安装，不包含在仓库源码或项目 Windows ZIP 中；原始 wheel 的许可及版权文件应随依赖保留。

| 依赖 | 版本 | 原始许可证 / 来源 |
| --- | --- | --- |
| aiohappyeyeballs | 2.7.1 | [PSF-2.0](https://github.com/aio-libs/aiohappyeyeballs/blob/main/LICENSE) |
| aiohttp | 3.14.3 | [Apache-2.0](https://github.com/aio-libs/aiohttp/blob/master/LICENSE.txt) **AND MIT**（其 wheel 内 `vendor/llhttp/LICENSE`） |
| aiosignal | 1.4.0 | [Apache-2.0](https://github.com/aio-libs/aiosignal/blob/master/LICENSE) |
| attrs | 26.1.0 | [MIT](https://github.com/python-attrs/attrs/blob/main/LICENSE) |
| frozenlist | 1.8.0 | [Apache-2.0](https://github.com/aio-libs/frozenlist/blob/master/LICENSE) |
| idna | 3.20 | [BSD-3-Clause](https://github.com/kjd/idna/blob/master/LICENSE.md) |
| multidict | 6.9.1 | [Apache-2.0](https://github.com/aio-libs/multidict/blob/master/LICENSE) |
| propcache | 0.5.4 | [Apache-2.0](https://github.com/aio-libs/propcache/blob/master/LICENSE)，附 `NOTICE` |
| yarl | 1.25.1 | [Apache-2.0](https://github.com/aio-libs/yarl/blob/master/LICENSE)，附 `NOTICE` |
| Pillow | 12.3.0 | [MIT-CMU](https://github.com/python-pillow/Pillow/blob/main/LICENSE)，其 wheel 内其他组件许可随依赖保留 |
| qrcode | 8.2 | [BSD-3-Clause](https://github.com/lincolnloop/python-qrcode/blob/v8.2/LICENSE)，用于本地生成付款二维码 |
| colorama | 0.4.6（Windows） | [BSD-3-Clause](https://github.com/tartley/colorama/blob/0.4.6/LICENSE.txt)，qrcode 的 Windows 终端依赖 |

## 图片回复字体

`starbridge/reply_font.py` 嵌入未修改的 **Noto Sans SC Regular** 字体，仅采用可逆的 LZMA / Base85 包装，以兼容现有升级器允许的文件类型。上游为 [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk/blob/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf)，固定提交 `f8d157532fbfaeda587e826d4cd5b21a49186f7c`，原始字体 SHA256 为 `faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9`。

字体自身的版权、名称与许可元数据完整保留，采用 **SIL Open Font License 1.1**，完整许可见 [noto-font-license.md](https://github.com/AlancoSage/StarBridge/blob/main/docs/noto-font-license.md)。生成脚本为 `scripts/build_reply_font.py`。该字体继续适用 OFL，与项目 AGPL 许可证分别声明。

`starbridge/reply_bold_font.py` 以相同方式嵌入未修改的 **Noto Sans SC Bold** 字体，供图片标题、统计数字与名单使用。来源为相同固定提交下的 [NotoSansSC-Bold.otf](https://github.com/notofonts/noto-cjk/blob/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/SubsetOTF/SC/NotoSansSC-Bold.otf)，原始字体 SHA256 为 `c6cb5a93abaa9edc8ee7463b7ebb7f42d618d40e6ed2f7a5371c97b0b64767c0`。可复现生成脚本为 `scripts/build_reply_bold_font.py`；原始版权、名称与许可元数据保留，继续适用上述 SIL OFL 1.1。

## 构建工具及运行环境提供的 API

Bot 的可选 MySQL 连接使用 [PyMySQL](https://github.com/PyMySQL/PyMySQL)（MIT），其 RSA / caching_sha2_password 认证依赖 [cryptography](https://github.com/pyca/cryptography)（Apache-2.0 OR BSD-3-Clause）、[cffi](https://github.com/python-cffi/cffi)（MIT-0）和 [pycparser](https://github.com/eliben/pycparser)（BSD-3-Clause）。这些组件通过 Python 依赖安装，保留各自软件包附带的许可证，不打入游戏端 JAR。MySQL 服务端不随部署包分发。

可选魔方财务模块也使用上述 cryptography 的 Fernet 加密账号 API 凭据及待确认的商品参数，使用 qrcode 与 Pillow 在本机生成 PNG 付款二维码。

以下是构建或运行环境使用的主要第三方组件，除上面明确列出的 Gson 和 Gradle Wrapper 外，其实现不被复制进 VexBot JAR：

| 组件 | 用途 / 声明位置 | 上游许可证 |
| --- | --- | --- |
| Spigot / Bukkit API | `bridge/pom.xml` 中的 `provided` 依赖 | [GPL-3.0](https://github.com/SpigotMC/Spigot-API/blob/master/LICENCE.txt) |
| Velocity API | `bridge-velocity/build.py` 的编译依赖，不随生产 JAR 打包 | [GPL-3.0](https://github.com/PaperMC/Velocity/blob/dev/3.0.0/LICENSE) |
| Forge / NeoForge | 游戏端运行 API、Gradle 编译依赖 | [Forge LGPL-2.1](https://github.com/MinecraftForge/MinecraftForge/blob/1.20.x/LICENSE.txt)、[NeoForge LGPL-2.1](https://github.com/neoforged/NeoForge/blob/1.21.x/LICENSE.txt) |
| Fabric Loader | `bridge-fabric/build.py` 的编译依赖 | [Apache-2.0](https://github.com/FabricMC/fabric-loader/blob/master/LICENSE) |
| SpongePowered Mixin | Fabric / NeoForge 注入 API | [MIT](https://github.com/SpongePowered/Mixin/blob/master/LICENSE.txt) |
| ASM 9.8 | Gson 重定位构建工具、Fabric 编译依赖 | [BSD-3-Clause](https://asm.ow2.io/license.html) |
| Brigadier 1.0.18 | Fabric 编译依赖 | [MIT](https://github.com/Mojang/brigadier/blob/master/LICENSE) |
| JUnit Jupiter 5.10.2 | Forge / NeoForge 测试依赖 | [EPL-2.0](https://github.com/junit-team/junit5/blob/r5.10.2/LICENSE.md) |

`bridge/src/*-test/java/` 下使用第三方包名的类是测试替身，不进入生产 JAR。AuthMe、LimboAuth、LibreLogin、LoginSecurity 与 nLogin 通过已安装插件的 API 接入，其插件实现不随 VexBot 分发。`bridge-velocity` 仅包含本项目代码及与 Bukkit 同版、同许可的重定位 Gson；测试期间使用的 Velocity、LimboAuth、LimboAPI、LibreLogin、H2 等正式 JAR 不进入生产附件。`starbridge-website/sdk/starbridge.js` 是 VexBot 的浏览器 API 客户端，适用项目许可证。

## Apache License 2.0

下列原文适用于上述 Gradle Wrapper 与 Gson；它不替代 VexBot 自有代码的 AGPL 许可证。

```text
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright [yyyy] [name of copyright owner]

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```
