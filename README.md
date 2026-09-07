# Atlas Sensors — BlueOS extension

An onboard BlueOS extension for the **Atlas EZO-DO circuit on the original ISCCB-2 isolated carrier from the dissolved oxygen kit, connected to a Navigator over I²C**. The Raspberry Pi runs the driver, logging and web server. The interface opens inside BlueOS. The deployment target is the BlueOS Extensions Manager.

Current release: **0.1.2-beta.1**. Only dissolved oxygen is implemented. This is an independent community integration, not an official Atlas Scientific product.

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

This uses GitHub’s build machines, so Docker Desktop is not needed on your computer.

1. Create a **public GitHub repository**, for example `blueos-atlas-sensors`.
2. Upload the **contents** of this source folder to its root. The repository root must contain `Dockerfile`, `VERSION`, `atlas/`, `scripts/`, `tests/`, and `.github/workflows/publish.yml`. Do not upload just the ZIP or nest everything inside an extra folder. Make sure the hidden `.github` folder is included. If using GitHub’s web uploader, you can create `.github/workflows/publish.yml` using **Add file → Create new file** and paste the included workflow if the folder was omitted.
3. In Docker Hub, create a **public** repository named `blueos-atlas-sensors`.
4. Create a Docker Hub access token with read/write permission. In the GitHub repository, open **Settings → Secrets and variables → Actions → Secrets**, and add:

   | Secret | Value |
   | --- | --- |
   | `DOCKER_USERNAME` | Your Docker Hub username, not your email |
   | `DOCKER_PASSWORD` | The Docker Hub access token |

5. In the same GitHub settings area, select **Variables** and add:

   | Variable | Value |
   | --- | --- |
   | `MY_NAME` | Your name or the name you maintain the extension under |
   | `MY_EMAIL` | A contact email you are comfortable including in public extension metadata |

6. Open **Actions → Build and publish BlueOS extension → Run workflow**, using the branch containing your files.
7. Wait for **both Pi image test jobs and the publish job** to pass. The workflow builds and runs tests inside both ARM images using QEMU, checks onboard hardware-mode startup without a sensor, then publishes the multi-architecture image. It finally verifies that Docker Hub’s manifest includes ARMv7 and ARM64.
8. From the completed workflow, download the **blueos-install-and-bazaar** artifact. Its `INSTALL.txt` contains the actual install fields for your account. The Docker Hub tag will be:

   ```text
   YOUR_DOCKER_USERNAME/blueos-atlas-sensors:0.1.2-beta.1
   ```

The workflow publishes only when manually run. For later changes, update `VERSION`, commit, and run it again. Use a new version rather than reusing a published tag.

## B. Put it on your Pi’s Extensions page

You can install your own image without waiting for public Bazaar approval.

1. Wire the original isolated carrier to the Navigator as described in **Navigator wiring** below. The EZO-DO must be in **I²C mode** (blue standby LED), normally address **97 / 0x61**.
2. Give the Pi internet access for the download and open its BlueOS interface.
3. Go to **Extensions → Installed → +** (the Add button).
4. Fill in:

   | BlueOS field | Value |
   | --- | --- |
   | Extension Identifier | `YOUR_DOCKER_USERNAME.atlas-sensors` |
   | Extension Name | `Atlas Sensors` |
   | Docker image | `YOUR_DOCKER_USERNAME/blueos-atlas-sensors` |
   | Docker tag | `0.1.2-beta.1` |
   | Custom settings | Paste the complete `blueos-settings.json` from this package or workflow artifact |

5. Submit the install. BlueOS downloads the matching ARM image, creates its container and manages its lifecycle. **Atlas Sensors** should appear on the Installed page and then in the sidebar after service discovery.
6. Open **Atlas Sensors** from the BlueOS sidebar. Select **Sensor · real measurements**, connection **I²C**, bus **`/dev/i2c-6`**, and address **`97`** (decimal, equivalent to `0x61`). The app lists Linux bus devices without scanning other sensors.
7. Set water temperature, salinity and surface atmospheric pressure, then click **Save & connect**. Baud rate does not apply to I²C.
8. Verify the identified EZO-DO, real readings, calibration status, recording/export and recovery after an extension restart.

The default port is allocated by BlueOS; there is no need to use localhost or manually start a server. Open it through BlueOS. Manage stop/start, restart, settings and uninstall through the Extensions Manager.

### Navigator wiring

Power the vehicle off before wiring. Use a Navigator **external I²C connector (bus 6)**, not the internal sensor bus. Match signal labels against the Navigator pinout; do not infer connector order from wire colors.

| Navigator external I²C signal | Original Atlas carrier pin |
| --- | --- |
| 3.3 V | VCC |
| GND | GND (host-side ground) |
| SDA | TX / SDA |
| SCL | RX / SCL |
| No connection | OFF — leave unconnected |

Connect the DO probe to the carrier’s SMA connector. The carrier has pull-ups and supports a 3.3 V input; using the Navigator 3.3 V supply keeps the host-side pull-ups at the correct level. Do not connect the isolated probe ground to host ground. Keep the I²C wiring short inside the dry enclosure.

**Switch the EZO-DO to I²C before connecting it to the Navigator bus.** It ships in UART mode. Follow the Atlas EZO-DO datasheet’s **Manual switching to I²C** procedure (printed page 36); this restores the default I²C address to 97. Use the circuit-side pins/PGND shown in that procedure, not a guessed short across the carrier’s host-side pins. Alternatively, if you already have a working UART connection, send `I2C,97` through that connection. The extension does not automatically change device protocol or address. Blue standby LED indicates I²C mode.

Blue Robotics documents external bus 6 for the Navigator. If `/dev/i2c-6` is absent, check the Navigator/BlueOS configuration; do not switch to an internal bus or change boot overlays at random.

Sources: [Atlas carrier pinout and isolation](https://files.atlas-scientific.com/electrically-isolated-ezo-carrier-board.pdf), [EZO-DO mode switching and protocol](https://files.atlas-scientific.com/DO_EZO_Datasheet.pdf), [Navigator device connection guide](https://bluerobotics.com/learn/connecting-your-device-with-navigator-and-blueos/).

### Upgrade from the USB version

After publishing tag `0.1.2-beta.1`, edit the installed extension in BlueOS: select the new tag **and replace Custom settings with the updated `blueos-settings.json`**. Old settings only allow USB serial devices; the new settings also permit Linux I²C devices. Save/restart, then select I²C, `/dev/i2c-6`, and address 97 in the dashboard. Legacy saved settings are migrated as UART to avoid silently redirecting an existing connection. Stop recording before changing the connection. Recording files remain in the persistent data directory.

### Device and storage permissions

`blueos-settings.json` mounts `/dev` and grants access to **I²C device major 89** and the existing **USB serial major 188**. No privileged mode or Docker socket is requested. The app opens only the bus/address or serial port you select. Native UART ports need their own device mapping/permissions and must be free from autopilot or serial-bridge use; the supported setup for your original carrier is Navigator I²C.

The persistent folder is `/usr/blueos/extensions/atlas-sensors` on the Pi, mounted at `/data`. Keep this mount across upgrades. Settings and recordings live there, not on your laptop. The image starts in hardware mode unless a user has explicitly saved demo mode in existing settings.

## C. Make it appear in the public Extensions store

The Installed page is your own vehicle’s installation list. The public Bazaar/store catalog requires a repository submission and maintainer acceptance.

After testing on your Pi and sensor:

1. Fork [BlueOS-Extensions-Repository](https://github.com/bluerobotics/BlueOS-Extensions-Repository).
2. The workflow artifact provides `repos/YOUR_DOCKER_USERNAME/atlas-sensors/metadata.json`, already filled with your image and GitHub URLs. Copy that `repos/` structure into your fork.
3. Add `extension_logo.png` beside `metadata.json`, and `company_logo.png` under `repos/YOUR_DOCKER_USERNAME/`. Use your own project/maintainer branding. These PNGs are not included because your branding has not been provided; they are unnecessary for installing on your own Pi.
4. Open a pull request to the BlueOS repository. Include what it supports and your Pi/BlueOS/sensor test results.
5. Address review feedback. Once maintainers merge it and the catalog updates, users can find and install it from the public Extensions store.

Publishing to Docker Hub alone does not create a public store listing. You do not need a Bazaar pull request to do section B.

## Onboard behavior and limitations

- Live mg/L, percent saturation and a trend graph, with explicit stale/disconnected states.
- Manual recording to SQLite and per-recording CSV downloads. UTC timestamps, real/demo mode, compensation inputs and calibration status are included. Recording does not resume automatically after restart.
- EZO-DO identity verification before configuration. Enables both output units and serializes commands with sampling. The I²C driver uses raw command bytes and binary response status, with processing delays and bounded busy retries. Continuous output is disabled only for UART connections.
- Manual temperature, salinity in ppt, and atmospheric pressure compensation, reapplied after reconnect. Defaults must be checked for your deployment. The atmospheric pressure field is not ROV depth pressure.
- Air and zero calibration controls require confirmation and stopped recording. Follow the [Atlas preparation and calibration procedure](https://files.atlas-scientific.com/DO_EZO_Datasheet.pdf). Existing calibration is not changed on startup.
- Demo mode is explicitly labeled and never used as an automatic fallback for failed hardware.
- Application reconnects after communication errors. No automatic address scanning or protocol switching is performed.
- Recordings are not automatically deleted. Download and manage storage periodically. The dashboard lists the latest 100 sessions; older data remains in SQLite.
- No Cockpit overlay or additional Atlas sensor driver yet. The driver is separate so those can be added later.

## Validation status

Local backend tests pass. The base image’s official architecture list includes ARM32v7 and ARM64v8. The supplied workflow is configured to build and test both Pi images before publishing.

**The ARM build workflow has not been run here, no image has been published to your account, and physical Navigator/I²C operation has not been verified.** Docker and access to your GitHub, Docker Hub and Pi were not available for those checks. Successful Actions runs establish container compatibility; the onboard checks in section B establish actual hardware behavior.

## Code layout

`atlas/sensors.py` handles the protocol; `atlas/service.py` handles sampling and storage; `atlas/__main__.py` serves the BlueOS API; `atlas/static/` contains the embedded interface. `Dockerfile` and `blueos-settings.json` define packaging. `.github/workflows/publish.yml` builds/tests/publishes the Pi images. `scripts/prepare_release.py` generates metadata and account-specific installation fields.

For development tests, install `requirements.txt` in Python 3.11+ and run `python -m unittest discover -s tests -v`.

References: [BlueOS extension development and manual installation](https://blueos.cloud/docs/stable/development/extensions/), [public catalog submission format](https://github.com/bluerobotics/BlueOS-Extensions-Repository), [official Python image architectures](https://github.com/docker-library/official-images/blob/master/library/python), [original isolated carrier](https://atlas-scientific.com/carrier-boards/electrically-isolated-ezo-carrier-board-gen-2/).
