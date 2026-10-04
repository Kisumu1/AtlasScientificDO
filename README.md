# Atlas Sensors — BlueOS extension

An onboard BlueOS extension for the **Atlas EZO-DO circuit**, connected through an Atlas USB serial carrier or the original ISCCB-2 isolated carrier over I²C. The Raspberry Pi runs the driver, logging and web server. The interface opens inside BlueOS. The deployment target is the BlueOS Extensions Manager.

Current release: **0.1.3-beta.1**. Only dissolved oxygen is implemented. This is an independent community integration, not an official Atlas Scientific product.

## What makes this a BlueOS extension

- Docker image with BlueOS `permissions`, `version`, `authors`, `company`, `readme`, `links`, `tags`, `type` and `requirements` labels.
- `/register_service` endpoint to register **Atlas Sensors** in the BlueOS sidebar.
- Relative frontend URLs for the BlueOS proxy/embedded interface.
- Persistent host storage for settings and recordings.
- I²C access to the Navigator external bus, with default EZO-DO address 97 (0x61). No USB carrier is required.
- GitHub Actions build, emulated tests and publishing for **linux/arm/v7** (32-bit ARM) and **linux/arm64** (64-bit ARM).
- A single published image tag containing both architectures. Docker on the Pi selects the appropriate image for its operating system.

No Python, Node or other application dependencies need to be installed manually on the Pi. They are included in the image. Internet access is needed to initially download the image; measurement and logging work offline afterward.

## A. Build and publish the installable image

This uses GitHub’s build machines and **GitHub Container Registry (GHCR)**. No Docker Hub account, Docker Desktop, manually created token, or Actions variables are needed for this path. The workflow uses GitHub's automatic `GITHUB_TOKEN` with `packages: write` permission, scoped to the publish job.

1. Create a **public GitHub repository**, for example `blueos-atlas-sensors`.
2. Upload the **contents** of this source folder to its root. The repository root must contain `Dockerfile`, `VERSION`, `atlas/`, `scripts/`, `tests/`, and `.github/workflows/publish.yml`. Do not upload just the ZIP or nest everything inside an extra folder. Make sure the hidden `.github` folder is included. If using GitHub’s web uploader, you can create `.github/workflows/publish.yml` using **Add file → Create new file** and paste the included workflow if the folder was omitted.
3. Open **Actions → Build and publish BlueOS extension → Run workflow**, select branch **main** and leave **registry** set to **ghcr**. Start a new run; re-running the old failed run uses its old code.
4. Wait for **both Pi image test jobs and the publish job** to pass. The workflow runs tests inside both ARM images using QEMU, checks onboard startup without a sensor, publishes the image and verifies its manifest includes ARMv7 and ARM64.
5. Open your GitHub **profile → Packages → blueos-atlas-sensors → Package settings → Change visibility → Public**, and confirm. **A public source repository does not automatically make the container package public.** BlueOS needs a public package to download it without credentials. For this repository, the package settings are [here](https://github.com/users/Kisumu1/packages/container/blueos-atlas-sensors/settings) after the first successful publish.
6. From the completed workflow, download the **blueos-install-and-bazaar** artifact. Its `INSTALL.txt` contains the actual install fields for your account, and `blueos-settings.json` contains the settings to paste into BlueOS. For this repository the image tag is:

   ```text
   ghcr.io/kisumu1/blueos-atlas-sensors:0.1.3-beta.1
   ```

GHCR publishing uses the GitHub repository owner and its GitHub noreply address for the required metadata labels; the source repository's Issues page is the support link. Old Docker Hub secrets and placeholder `MY_NAME`/`MY_EMAIL` variables are unused when `registry=ghcr`.

The workflow publishes only when manually run. For later changes, update `VERSION`, commit, and run it again. Use a new version rather than reusing a published tag. See section C for optional Docker Hub publishing.

If installation reports `denied` or `unauthorized`, confirm the **container package** visibility is Public. If you still see `DOCKER_USERNAME must be ...`, you selected Docker Hub or re-ran the old workflow; start a new run on main with registry `ghcr`.

References: [GitHub Container Registry authentication and visibility](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry), [package visibility settings](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility). BlueOS's [manual installer](https://github.com/bluerobotics/BlueOS/blob/1.4.3/core/services/kraken/extension/extension.py) passes the supplied image reference to Docker, which allows a `ghcr.io/...` image.

## B. Put it on your Pi’s Extensions page

You can install your own image without waiting for public Bazaar approval.

1. For your **USB EZO carrier**, connect the EZO-DO and probe to the carrier and plug its USB cable into the **Pi running BlueOS**. The sensor must be in **UART mode** (green standby LED), normally **9600 baud**. For the original carrier, use the I²C connection described below instead.
2. Give the Pi internet access for the download and open its BlueOS interface.
3. Go to **Extensions → Installed → +** (the Add button).
4. Fill in:

   | BlueOS field | Value |
   | --- | --- |
   | Extension Identifier | `kisumu1.atlas-sensors` |
   | Extension Name | `Atlas Sensors` |
   | Docker image | `ghcr.io/kisumu1/blueos-atlas-sensors` |
   | Docker tag | `0.1.3-beta.1` |
   | Custom settings | Paste the complete `blueos-settings.json` from this package or workflow artifact |

5. Submit the install. BlueOS downloads the matching ARM image, creates its container and manages its lifecycle. **Atlas Sensors** should appear on the Installed page and then in the sidebar after service discovery.
6. Open **Atlas Sensors** from the BlueOS sidebar. Open **Sensor settings**, check the compensation values, and use **USB carrier** with **9600 baud** unless you previously changed it. Click **Find & connect** to automatically identify the sensor, select its USB port, save the settings, and start readings. For an I²C connection instead, select **I²C**, bus **`/dev/i2c-6`**, and address **`97`** (decimal, equivalent to `0x61`).
7. **Find & connect** needs no additional Save click. To change settings afterward or connect to a manually selected port, set water temperature, salinity and surface atmospheric pressure, then click **Apply settings**. Baud rate does not apply to I²C.
8. Verify the identified EZO-DO, real readings, calibration status, recording/export and recovery after an extension restart.

The default port is allocated by BlueOS; there is no need to use localhost or manually start a server. Open it through BlueOS. Manage stop/start, restart, settings and uninstall through the Extensions Manager.

### USB connection troubleshooting

`/dev/ttyAMA1` is an onboard UART, not the USB carrier. The extension does not grant access to onboard UARTs. Choose **USB carrier**, click **Find & connect** to identify, verify a reading, and automatically save the carrier's `/dev/ttyUSB...` device or `/dev/serial/by-id/...` entry. Start at 9600 baud unless you changed the EZO baud rate. USB listings are candidates; the driver verifies EZO-DO identity before applying settings.

If no USB device appears, check that the carrier is plugged into the BlueOS Pi with a USB data cable, then click Find & connect again. Disconnect/reconnect the carrier to see which entry disappears/reappears. Device discovery also checks the mounted `/dev` nodes when container sysfs metadata is missing. For this upgrade, replace Custom settings with this repository's `blueos-settings.json` to include ttyACM permissions.

### Navigator wiring

Power the vehicle off before wiring. Use a Navigator **external I²C connector (bus 6)**, not the internal sensor bus. Match signal labels against the Navigator pinout; do not infer connector order from wire colors.

| Host-side connection | Original Atlas carrier pin |
| --- | --- |
| Regulated 3.3 V supply | VCC |
| Common host GND | GND (host-side ground) |
| Navigator external SDA | TX / SDA |
| Navigator external SCL | RX / SCL |
| No connection | OFF — leave unconnected |

Connect the DO probe to the carrier’s SMA connector. The carrier has host-side pull-ups tied to VCC; powering it at 3.3 V keeps them at 3.3 V. Verify your Navigator revision's connector power voltage against its actual pinout before wiring. If its power pin supplies 5 V, use a separate regulated 3.3 V supply with common host ground, or a suitable I²C level converter; do not assume that pin supplies 3.3 V. Do not connect the isolated probe ground to host ground. Keep the I²C wiring short inside the dry enclosure. A USB carrier avoids this wiring.

**Switch the EZO-DO to I²C before connecting it to the Navigator bus.** It ships in UART mode. Follow the Atlas EZO-DO datasheet’s **Manual switching to I²C** procedure; this restores the default I²C address to 97. Use the circuit-side pins/PGND shown in that procedure, not a guessed short across the carrier’s host-side pins. Alternatively, if you already have a working UART connection, send `I2C,97` through that connection. The extension does not automatically change device protocol or address. Blue standby LED indicates I²C mode. Keep UART mode for a USB serial carrier.

Blue Robotics documents external bus 6 for the Navigator. If `/dev/i2c-6` is absent, check the Navigator/BlueOS configuration; do not switch to an internal bus or change boot overlays at random.

Sources: [Atlas carrier pinout and isolation](https://files.atlas-scientific.com/electrically-isolated-ezo-carrier-board.pdf), [EZO-DO mode switching and protocol](https://files.atlas-scientific.com/DO_EZO_Datasheet.pdf), [Navigator device connection guide](https://bluerobotics.com/learn/connecting-your-device-with-navigator-and-blueos/).

### Upgrade from the USB version

After publishing tag `0.1.3-beta.1`, edit the installed extension in BlueOS: select the new tag **and replace Custom settings with the updated `blueos-settings.json`**. Old settings only allow USB serial devices; the new settings also permit Linux I²C devices. Save/restart, then select I²C, `/dev/i2c-6`, and address 97 in the dashboard. Legacy saved settings are migrated as UART to avoid silently redirecting an existing connection. Stop recording before changing the connection. Recording files remain in the persistent data directory.

### Device and storage permissions

`blueos-settings.json` mounts `/dev` and grants access to **I²C device major 89** and **USB serial majors 188 (ttyUSB) and 166 (ttyACM)**. No privileged mode or Docker socket is requested. The app opens only the bus/address or serial port you select. Native UART ports need their own device mapping/permissions and must be free from autopilot or serial-bridge use; the supported setup for your original carrier is Navigator I²C.

The persistent folder is `/usr/blueos/extensions/atlas-sensors` on the Pi, mounted at `/data`. Keep this mount across upgrades. Settings and recordings live there, not on your laptop. The image starts in hardware mode unless a user has explicitly saved demo mode in existing settings.

## C. Make it appear in the public Extensions store

The Installed page is your own vehicle’s installation list. GHCR is suitable for the manual install above. The public Bazaar/store catalog currently expects images hosted on **Docker Hub**, plus a repository submission and maintainer acceptance. Do not submit GHCR-only registration metadata as though it were a Docker Hub image.

To publish to Docker Hub later:

1. Create a Docker Hub account and a **public** repository named `blueos-atlas-sensors`.
2. In GitHub **Settings → Secrets and variables → Actions → Secrets**, set `DOCKER_USERNAME` to your actual Docker ID (not an email or URL) and `DOCKER_PASSWORD` to a Docker Hub access token with read/write permission.
3. Under **Variables**, set `MY_NAME` to your maintainer name and `MY_EMAIL` to a real contact email suitable for public metadata. The literal values `name` and `email` are placeholders.
4. Run a **new** workflow on main and select **registry: dockerhub**. Its artifact includes Docker Hub install fields and `repos/YOUR_DOCKER_USERNAME/atlas-sensors/metadata.json`. The Docker Hub image is `YOUR_DOCKER_USERNAME/blueos-atlas-sensors:0.1.3-beta.1`.

After testing on your Pi and sensor:

1. Fork [BlueOS-Extensions-Repository](https://github.com/bluerobotics/BlueOS-Extensions-Repository).
2. The workflow artifact provides `repos/YOUR_DOCKER_USERNAME/atlas-sensors/metadata.json`, already filled with your image and GitHub URLs. Copy that `repos/` structure into your fork.
3. Add `extension_logo.png` beside `metadata.json`, and `company_logo.png` under `repos/YOUR_DOCKER_USERNAME/`. Use your own project/maintainer branding. These PNGs are not included because your branding has not been provided; they are unnecessary for installing on your own Pi.
4. Open a pull request to the BlueOS repository. Include what it supports and your Pi/BlueOS/sensor test results.
5. Address review feedback. Once maintainers merge it and the catalog updates, users can find and install it from the public Extensions store.

Publishing a container image alone does not create a public store listing. You do not need a Bazaar pull request to do section B.

## Onboard behavior and limitations

- A simple main screen with Find & connect, mg/L, percent saturation and recording. Sensor settings, history, saved recordings and calibration are expandable. Connection errors use plain language with original technical details available underneath. New installations default to USB; saved I2C settings are preserved.
- Manual recording to SQLite and per-recording CSV downloads. UTC timestamps, real/demo mode, compensation inputs and calibration status are included. Recording does not resume automatically after restart.
- EZO-DO identity verification before configuration. Accepts both the older `?i,D.O.,...` response and `?I,DO,2.17` observed on the actual USB sensor; response prefixes are case-insensitive. Enables both output units and serializes commands with sampling. The I²C driver uses raw command bytes and binary response status, with processing delays and bounded busy retries. Continuous output is disabled only for UART connections.
- Manual temperature, salinity in ppt, and atmospheric pressure compensation, reapplied after reconnect. Defaults must be checked for your deployment. The atmospheric pressure field is not ROV depth pressure.
- Air and zero calibration controls require confirmation and stopped recording. Follow the [Atlas preparation and calibration procedure](https://files.atlas-scientific.com/DO_EZO_Datasheet.pdf). Existing calibration is not changed on startup.
- Demo mode is explicitly labeled and never used as an automatic fallback for failed hardware.
- **Find & connect** tries available USB serial ports at the selected baud rate, verifies EZO-DO identity and a reading, saves the working port, and connects automatically. USB aliases are deduplicated. It uses the current compensation values and never changes calibration. For I2C it checks only the selected bus/address (default external bus 6, address 97). Application reconnects after communication errors. No automatic address scanning or protocol switching is performed.
- Recordings are not automatically deleted. Download and manage storage periodically. The dashboard lists the latest 100 sessions; older data remains in SQLite.
- No Cockpit overlay or additional Atlas sensor driver yet. The driver is separate so those can be added later.

## Validation status

Local backend and release metadata tests pass. Both **ARMv7 and ARM64** image builds, backend tests and onboard startup checks passed in [the October 3, 2026 Actions run](https://github.com/Kisumu1/AtlasScientificDO/actions/runs/37154324868). That run failed before publishing because Docker Hub configuration was invalid; the updated workflow uses GHCR by default and current actions with Node.js 24 support.

Physical USB operation was verified on October 3, 2026 on BlueOS 1.4.6 with an FTDI FT230X USB carrier and EZO-DO firmware 2.17. Version 0.1.2-beta.5 identified the circuit, connected automatically, saved its stable USB port, and displayed live mg/L and saturation readings. Calibration and recording were not changed during this check. All 26 tests and startup checks passed on ARMv7 and ARM64 in [the successful release run](https://github.com/Kisumu1/AtlasScientificDO/actions/runs/37165143922). Navigator/I²C hardware operation remains unverified.

## Code layout

`atlas/sensors.py` handles the protocol; `atlas/service.py` handles sampling and storage; `atlas/__main__.py` serves the BlueOS API; `atlas/static/` contains the embedded interface. `Dockerfile` and `blueos-settings.json` define packaging. `.github/workflows/publish.yml` builds/tests/publishes the Pi images. `scripts/prepare_release.py` generates metadata and account-specific installation fields.

For development tests, install `requirements.txt` in Python 3.11+ and run `python -m unittest discover -s tests -v`.

References: [BlueOS extension development and manual installation](https://blueos.cloud/docs/stable/development/extensions/), [public catalog submission format](https://github.com/bluerobotics/BlueOS-Extensions-Repository), [official Python image architectures](https://github.com/docker-library/official-images/blob/master/library/python), [original isolated carrier](https://atlas-scientific.com/carrier-boards/electrically-isolated-ezo-carrier-board-gen-2/).

## Cockpit widget

Connect the sensor in Atlas Sensors first. In Cockpit, enter **Edit mode**, open the widget picker, and add **Atlas Dissolved Oxygen**. Resize and position it, then exit Edit mode. Reload Cockpit after installing or upgrading the extension if the widget does not appear.

The readout shares the extension's sensor connection and displays mg/L, saturation, and reading age. Disconnected or expired readings display dashes. Simulated readings are marked DEMO. No additional serial connection or permissions are needed.

For a manual IFrame widget, use `http://BLUEOS_ADDRESS/extensionv2/atlassensors/widget.html` as its source URL. The same page is available through **Cockpit widget > Preview widget** on the dashboard. Discovery follows [Cockpit's extension metadata interface](https://github.com/bluerobotics/cockpit/blob/v1.16.0-beta.8/src/libs/blueos.ts); metadata supports the installed snake_case interface and newer camelCase widget fields.

Version 0.1.3-beta.1 was verified on the same Pi and USB sensor: BlueOS discovered the Cockpit metadata, Cockpit v1.16.0-beta.8 listed Atlas Dissolved Oxygen, and the added widget displayed live mg/L and saturation. The sensor reconnected using its saved USB settings after the update. Python tests, widget state tests, and both ARM startup checks passed in [the release run](https://github.com/Kisumu1/AtlasScientificDO/actions/runs/37167218655).
