// linux-magnify Settings (Quickshell).
//
// Reads and writes the config through `python -m linux_magnify --config-json /
// --config-set`, so Python stays the only thing that touches the TOML file. The
// running dock watches that file and applies every change immediately.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

ShellRoot {
    id: root

    readonly property string python: Quickshell.env("MAGDOC_PYTHON") || "python3"
    property var cfg: ({})
    property bool ready: false
    property bool running: false
    property bool autostart: false
    property var pending: ({})
    property var allApps: []
    property var upd: ({})
    property bool updating: false
    property string appQuery: ""

    readonly property var positions: ["bottom", "top", "left", "right"]
    readonly property var positionLabels: ["Bottom", "Top", "Left", "Right"]
    readonly property var hideModes: ["auto", "never", "dodge", "always"]
    readonly property var hideModeLabels: ["Same as original panel", "Always visible",
                                           "Hide when a window covers it", "Always auto-hide"]
    readonly property var hidePanels: ["all", "dock", "none"]
    readonly property var hidePanelLabels: ["Every panel and dock (only magdoc)",
                                            "Panels on the dock's edge, and other docks", "Don't hide anything"]

    function cmd(args) { return [root.python, "-m", "linux_magnify"].concat(args); }

    // Batch quick changes (sliders, spin boxes) into one write.
    function set(key, value) {
        if (!root.ready) return;
        const p = Object.assign({}, root.pending);
        p[key] = value;
        root.pending = p;
        saveTimer.restart();
    }

    // Structural changes (pinned list): write now, then reload to show the result.
    function setNow(changes) {
        Quickshell.execDetached(root.cmd(["--config-set", JSON.stringify(changes)]));
        reloadTimer.restart();
    }

    function iconSource(name, fallback) {
        const n = name && name !== "auto" ? name : fallback;
        return n.startsWith("/") ? "file://" + n : Quickshell.iconPath(n, fallback);
    }

    function parseColor(text) {
        const m = /rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)/.exec(text || "");
        if (m) return Qt.rgba(m[1] / 255, m[2] / 255, m[3] / 255, m[4] === undefined ? 1 : Number(m[4]));
        return text || "transparent";
    }

    function movePinned(i, delta) {
        const list = root.cfg.pinned.slice();
        const t = list[i]; list[i] = list[i + delta]; list[i + delta] = t;
        root.setNow({ pinned: list });
    }

    function removePinned(i) {
        const list = root.cfg.pinned.slice();
        list.splice(i, 1);
        root.setNow({ pinned: list });
    }

    function addPinned(id) {
        const list = (root.cfg.pinned || []).slice();
        list.push({ id: id });
        root.setNow({ pinned: list });
    }

    Timer {
        id: saveTimer
        interval: 300
        onTriggered: {
            Quickshell.execDetached(root.cmd(["--config-set", JSON.stringify(root.pending)]));
            root.pending = ({});
        }
    }
    Timer { id: reloadTimer; interval: 700; onTriggered: loader.running = true }

    Process {
        id: loader
        command: root.cmd(["--config-json"])
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.cfg = JSON.parse(text); root.ready = true; }
                catch (e) { console.warn("linux-magnify: could not read config:", e); }
            }
        }
    }

    Process {
        id: statusProc
        command: root.cmd(["--status-json"])
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                try { const s = JSON.parse(text); root.running = s.running; root.autostart = s.autostart; }
                catch (e) {}
            }
        }
    }
    Timer { interval: 2000; running: true; repeat: true; onTriggered: statusProc.running = true }

    Process {
        id: updProc
        command: root.cmd(["--updates-json"])
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.upd = JSON.parse(text); root.updating = root.upd.updating === true; } catch (e) {}
            }
        }
    }
    Timer { id: updRecheck; interval: 15000; onTriggered: updProc.running = true }

    function shortSha(sha) { return sha ? sha.substring(0, 7) : "unknown"; }

    Process {
        id: appsProc
        command: root.cmd(["--apps-json"])
        stdout: StdioCollector {
            onStreamFinished: { try { root.allApps = JSON.parse(text); } catch (e) {} }
        }
    }

    // ------------------------------------------------------------ building blocks
    component Card: Rectangle {
        id: card
        default property alias content: column.data
        property string heading: ""
        SystemPalette { id: cardPal }
        Layout.fillWidth: true
        implicitHeight: column.implicitHeight + 24
        radius: 12
        color: Qt.tint(cardPal.window, Qt.rgba(1, 1, 1, 0.05))
        border.color: Qt.rgba(cardPal.windowText.r, cardPal.windowText.g, cardPal.windowText.b, 0.12)
        ColumnLayout {
            id: column
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
            spacing: 10
        }
    }

    component SettingRow: RowLayout {
        id: row
        property string title: ""
        property string subtitle: ""
        default property alias control: holder.data
        Layout.fillWidth: true
        spacing: 16
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Label { text: row.title; font.pixelSize: 14; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Label {
                text: row.subtitle; visible: row.subtitle !== ""; opacity: 0.65; font.pixelSize: 12
                Layout.fillWidth: true; wrapMode: Text.WordWrap
            }
        }
        Item {
            id: holder
            Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
            implicitWidth: childrenRect.width
            implicitHeight: childrenRect.height
        }
    }

    component Heading: Label {
        font.pixelSize: 13
        font.bold: true
        opacity: 0.8
        Layout.topMargin: 6
    }

    component ColourRow: SettingRow {
        id: colourRow
        property string key: ""
        property string value: ""
        signal edited(string text)
        function toColour(text) {
            const m = /rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)/.exec(text || "");
            if (m) return Qt.rgba(m[1] / 255, m[2] / 255, m[3] / 255, m[4] === undefined ? 1 : Number(m[4]));
            return text || "transparent";
        }
        RowLayout {
            spacing: 8
            Rectangle {
                width: 28; height: 28; radius: 6
                color: colourRow.toColour(colourField.text)
                border.color: Qt.rgba(0.5, 0.5, 0.5, 0.6)
            }
            TextField {
                id: colourField
                implicitWidth: 230
                text: colourRow.value
                onEditingFinished: colourRow.edited(text)
            }
        }
    }

    // ------------------------------------------------------------------- window
    FloatingWindow {
        id: win
        title: "linux-magnify Settings"
        implicitWidth: 860
        implicitHeight: 660
        color: pal.window
        onVisibleChanged: if (!visible) Qt.quit()

        SystemPalette { id: pal }

        RowLayout {
            anchors.fill: parent
            spacing: 0

            // Sidebar
            Rectangle {
                Layout.fillHeight: true
                Layout.preferredWidth: 200
                color: Qt.tint(pal.window, Qt.rgba(0, 0, 0, 0.12))

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 4

                    RowLayout {
                        Layout.bottomMargin: 12
                        spacing: 10
                        Image {
                            width: 32; height: 32
                            sourceSize.width: 64; sourceSize.height: 64
                            source: root.iconSource(root.cfg.home_detected ? root.cfg.home_detected.icon : "", "start-here")
                        }
                        Label { text: "linux-magnify"; font.pixelSize: 20; font.bold: true; color: pal.windowText }
                    }

                    Repeater {
                        model: ["General", "Appearance", "Apps", "Home Button", "Updates", "About"]
                        delegate: ItemDelegate {
                            required property string modelData
                            required property int index
                            Layout.fillWidth: true
                            text: modelData === "Updates" && root.upd.available ? "Updates  ●" : modelData
                            highlighted: pages.currentIndex === index
                            onClicked: pages.currentIndex = index
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Label {
                        text: root.running ? "● Running" : "○ Stopped"
                        color: root.running ? "#2ec27e" : pal.windowText
                        opacity: root.running ? 1 : 0.6
                    }
                }
            }

            StackLayout {
                id: pages
                Layout.fillWidth: true
                Layout.fillHeight: true

                // ------------------------------------------------------- General
                ScrollView {
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width - 40
                        x: 20; y: 20
                        spacing: 12

                        Card {
                            SettingRow {
                                title: "Enable linux-magnify magdoc"
                                subtitle: "Starts magdoc now and every time you log in, and hides your original panels "
                                          + "all the time. Turn off to stop magdoc and bring your panels back."
                                Switch {
                                    checked: root.running || root.autostart
                                    onToggled: Quickshell.execDetached(root.cmd([checked ? "--enable" : "--disable"]))
                                }
                            }
                            RowLayout {
                                spacing: 8
                                Button {
                                    text: root.running ? "Turn Off magdoc" : "Turn On magdoc"
                                    onClicked: Quickshell.execDetached(root.cmd([root.running ? "--disable" : "--enable"]))
                                }
                                Label {
                                    opacity: 0.65
                                    text: root.running ? "magdoc is running." : "magdoc is off."
                                }
                            }
                        }

                        Heading { text: "Dock" }
                        Card {
                            SettingRow {
                                title: "Position"; subtitle: "Screen edge for the dock"
                                ComboBox {
                                    implicitWidth: 200
                                    model: root.positionLabels
                                    currentIndex: Math.max(0, root.positions.indexOf(root.cfg.position))
                                    onActivated: index => root.set("position", root.positions[index])
                                }
                            }
                            SettingRow {
                                title: "Monitor"; subtitle: "0 is the primary monitor"
                                SpinBox {
                                    from: 0; to: 8
                                    value: root.cfg.monitor || 0
                                    onValueModified: root.set("monitor", value)
                                }
                            }
                            SettingRow {
                                title: "Hiding"
                                subtitle: "When the dock is hidden, push the pointer against the screen edge to show it."
                                ComboBox {
                                    implicitWidth: 260
                                    model: root.hideModeLabels
                                    currentIndex: Math.max(0, root.hideModes.indexOf(root.cfg.hide_mode))
                                    onActivated: index => root.set("hide_mode", root.hideModes[index])
                                }
                            }
                            SettingRow {
                                title: "Show app names"; subtitle: "Label above the hovered icon"
                                Switch { checked: root.cfg.show_labels === true; onToggled: root.set("show_labels", checked) }
                            }
                            SettingRow {
                                title: "Show open apps"; subtitle: "Also show running apps that aren't pinned"
                                Switch { checked: root.cfg.show_running === true; onToggled: root.set("show_running", checked) }
                            }
                        }

                        Heading { text: "Original panels" }
                        Card {
                            SettingRow {
                                title: "Hide the original panels"
                                subtitle: "Hidden all the time while linux-magnify is enabled, also after logging in again. "
                                          + "On Plasma the panels are removed and come back exactly as they were "
                                          + "when you turn linux-magnify off."
                                ComboBox {
                                    implicitWidth: 300
                                    model: root.hidePanelLabels
                                    currentIndex: Math.max(0, root.hidePanels.indexOf(root.cfg.hide_panels))
                                    onActivated: index => root.set("hide_panels", root.hidePanels[index])
                                }
                            }
                        }
                        Item { implicitHeight: 20 }
                    }
                }

                // ---------------------------------------------------- Appearance
                ScrollView {
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width - 40
                        x: 20; y: 20
                        spacing: 12

                        Heading { text: "Magnification" }
                        Card {
                            SettingRow {
                                title: "Icon size"; subtitle: "Resting size in pixels"
                                SpinBox {
                                    from: 16; to: 128; stepSize: 2
                                    value: root.cfg.icon_size || 48
                                    onValueModified: root.set("icon_size", value)
                                }
                            }
                            SettingRow {
                                title: "Magnification"; subtitle: "How big the icon under the pointer grows (1 = off)"
                                RowLayout {
                                    Slider {
                                        id: magSlider
                                        implicitWidth: 220
                                        from: 1; to: 4; stepSize: 0.1
                                        value: root.cfg.magnification || 2
                                        onMoved: root.set("magnification", Math.round(value * 10) / 10)
                                    }
                                    Label { text: magSlider.value.toFixed(1) + "×"; Layout.preferredWidth: 40 }
                                }
                            }
                            SettingRow {
                                title: "Spread"; subtitle: "How many neighbouring icons grow too"
                                RowLayout {
                                    Slider {
                                        id: spreadSlider
                                        implicitWidth: 220
                                        from: 1; to: 6; stepSize: 0.5
                                        value: root.cfg.spread || 3
                                        onMoved: root.set("spread", value)
                                    }
                                    Label { text: spreadSlider.value.toFixed(1); Layout.preferredWidth: 40 }
                                }
                            }
                            SettingRow {
                                title: "Animation speed"; subtitle: "Smoothing time in milliseconds (lower is snappier)"
                                SpinBox {
                                    from: 20; to: 400; stepSize: 10
                                    value: root.cfg.animation_ms || 90
                                    onValueModified: root.set("animation_ms", value)
                                }
                            }
                        }

                        Heading { text: "Layout" }
                        Card {
                            Repeater {
                                model: [
                                    { key: "spacing", title: "Spacing", sub: "Gap between icons", max: 48 },
                                    { key: "padding", title: "Padding", sub: "Space around the icons inside the shelf", max: 48 },
                                    { key: "margin", title: "Margin", sub: "Gap between the shelf and the screen edge", max: 96 },
                                    { key: "corner_radius", title: "Corner radius", sub: "", max: 64 }
                                ]
                                delegate: SettingRow {
                                    required property var modelData
                                    title: modelData.title
                                    subtitle: modelData.sub
                                    SpinBox {
                                        from: 0; to: modelData.max
                                        value: root.cfg[modelData.key] || 0
                                        onValueModified: root.set(modelData.key, value)
                                    }
                                }
                            }
                        }

                        Heading { text: "Colours" }
                        Card {
                            Repeater {
                                model: [
                                    { key: "background", title: "Shelf background" },
                                    { key: "border", title: "Shelf border" },
                                    { key: "indicator", title: "Running indicator" },
                                    { key: "label_background", title: "Label background" },
                                    { key: "label_foreground", title: "Label text" }
                                ]
                                delegate: ColourRow {
                                    required property var modelData
                                    title: modelData.title
                                    subtitle: "CSS colour, e.g. rgba(28, 28, 32, 0.55)"
                                    value: root.cfg[modelData.key] || ""
                                    onEdited: text => root.set(modelData.key, text)
                                }
                            }
                        }
                        Item { implicitHeight: 20 }
                    }
                }

                // ---------------------------------------------------------- Apps
                ScrollView {
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width - 40
                        x: 20; y: 20
                        spacing: 12

                        Heading { text: "Pinned apps" }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            opacity: 0.7
                            text: root.cfg.pinned_imported
                                  ? "Copied from your original panel and kept in sync with it until you change this list. "
                                    + "You can also right-click icons in the dock to pin or unpin them."
                                  : "Open apps that aren't pinned still show up while they run. "
                                    + "You can also right-click icons in the dock to pin or unpin them."
                        }
                        Card {
                            Label {
                                visible: !(root.cfg.pinned_display && root.cfg.pinned_display.length)
                                text: "No pinned apps. Use “Add App…” below."
                                opacity: 0.7
                            }
                            Repeater {
                                model: root.cfg.pinned_display || []
                                delegate: RowLayout {
                                    required property var modelData
                                    required property int index
                                    Layout.fillWidth: true
                                    spacing: 12
                                    Image {
                                        width: 32; height: 32
                                        sourceSize.width: 64; sourceSize.height: 64
                                        source: root.iconSource(modelData.icon, "application-x-executable")
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 0
                                        Label { text: modelData.name; font.pixelSize: 14 }
                                        Label { text: "Not installed"; visible: !modelData.installed; opacity: 0.6; font.pixelSize: 12 }
                                    }
                                    ToolButton {
                                        icon.name: "go-up"; enabled: index > 0
                                        ToolTip.text: "Move up"; ToolTip.visible: hovered
                                        onClicked: root.movePinned(index, -1)
                                    }
                                    ToolButton {
                                        icon.name: "go-down"; enabled: index < root.cfg.pinned_display.length - 1
                                        ToolTip.text: "Move down"; ToolTip.visible: hovered
                                        onClicked: root.movePinned(index, 1)
                                    }
                                    ToolButton {
                                        icon.name: "edit-delete"
                                        ToolTip.text: "Unpin"; ToolTip.visible: hovered
                                        onClicked: root.removePinned(index)
                                    }
                                }
                            }
                        }
                        RowLayout {
                            spacing: 8
                            Button {
                                text: "Add App…"
                                highlighted: true
                                onClicked: { appsProc.running = true; addPopup.open(); }
                            }
                            Button {
                                text: "Copy From Original Panel"
                                onClicked: root.setNow({ pinned: "import" })
                            }
                        }
                        Item { implicitHeight: 20 }
                    }
                }

                // --------------------------------------------------- Home button
                ScrollView {
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width - 40
                        x: 20; y: 20
                        spacing: 12

                        Card {
                            SettingRow {
                                title: "Show the home button"
                                subtitle: "First icon on the dock. Opens the start menu (the Meta key does too on Plasma)."
                                Switch { checked: root.cfg.home_enabled === true; onToggled: root.set("home_enabled", checked) }
                            }
                            SettingRow {
                                title: "Icon"
                                subtitle: "Copied from: " + (root.cfg.home_detected ? root.cfg.home_detected.source : "")
                                Image {
                                    width: 48; height: 48
                                    sourceSize.width: 96; sourceSize.height: 96
                                    source: root.iconSource(root.cfg.home_icon,
                                                            root.cfg.home_detected ? root.cfg.home_detected.icon : "start-here")
                                }
                            }
                        }

                        Heading { text: "Override (leave empty for automatic)" }
                        Card {
                            SettingRow {
                                title: "Icon name or file"; subtitle: "e.g. start-here, archlinux-logo, /path/to/logo.svg"
                                TextField {
                                    implicitWidth: 280
                                    text: root.cfg.home_icon && root.cfg.home_icon !== "auto" ? root.cfg.home_icon : ""
                                    placeholderText: "auto (" + (root.cfg.home_detected ? root.cfg.home_detected.icon : "") + ")"
                                    onEditingFinished: root.set("home_icon", text.trim() || "auto")
                                }
                            }
                            SettingRow {
                                title: "Command"; subtitle: "Runs when the button is clicked, e.g. rofi -show drun"
                                TextField {
                                    implicitWidth: 280
                                    text: root.cfg.home_command && root.cfg.home_command !== "auto" ? root.cfg.home_command : ""
                                    placeholderText: "auto (" + (root.cfg.home_detected ? root.cfg.home_detected.command : "") + ")"
                                    onEditingFinished: root.set("home_command", text.trim() || "auto")
                                }
                            }
                            SettingRow {
                                title: "Try the button"
                                Button { text: "Test"; onClicked: Quickshell.execDetached(root.cmd(["--home"])) }
                            }
                        }
                        Item { implicitHeight: 20 }
                    }
                }

                // ------------------------------------------------------- Updates
                ScrollView {
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width - 40
                        x: 20; y: 20
                        spacing: 12

                        Card {
                            Label {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                font.pixelSize: 16
                                font.bold: true
                                text: root.updating ? "Updating linux-magnify…"
                                      : root.upd.available ? "A new version of linux-magnify is available"
                                      : root.upd.error ? "Couldn't check for updates"
                                      : root.upd.installed ? "linux-magnify is up to date" : "Checking for updates…"
                            }
                            Label {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                opacity: 0.75
                                visible: text !== ""
                                text: root.upd.error ? root.upd.error
                                      : root.upd.available ? root.shortSha(root.upd.latest) + ": " + (root.upd.message || "")
                                                             + (root.upd.date ? "  (" + root.upd.date.substring(0, 10) + ")" : "")
                                      : ""
                            }
                            SettingRow {
                                title: "Installed version"
                                subtitle: "linux-magnify " + (root.upd.version || "") + ", build " + root.shortSha(root.upd.installed)
                            }
                            RowLayout {
                                spacing: 8
                                Button {
                                    text: "Update Now"
                                    highlighted: true
                                    enabled: root.upd.available === true && !root.updating
                                    onClicked: {
                                        root.updating = true;
                                        Quickshell.execDetached(root.cmd(["--update"]));
                                        updRecheck.restart();
                                    }
                                }
                                Button {
                                    text: "Check Now"
                                    enabled: !updProc.running && !root.updating
                                    onClicked: updProc.running = true
                                }
                            }
                        }

                        Card {
                            SettingRow {
                                title: "Notify me about new versions"
                                subtitle: "linux-magnify checks GitHub every few hours and shows a notification with an "
                                          + "“Update now” button when a new version is out."
                                Switch {
                                    checked: root.cfg.update_notify !== false
                                    onToggled: root.set("update_notify", checked)
                                }
                            }
                        }
                        Item { implicitHeight: 20 }
                    }
                }

                // --------------------------------------------------------- About
                ScrollView {
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width - 40
                        x: 20; y: 20
                        spacing: 10
                        Label { text: "linux-magnify " + (root.cfg.version || ""); font.pixelSize: 24; font.bold: true }
                        Label {
                            Layout.fillWidth: true; wrapMode: Text.WordWrap
                            text: "A macOS-style magnifying dock for KDE Plasma, Hyprland, Sway, niri, Xfce, "
                                  + "Cinnamon, MATE and other Linux desktops."
                        }
                        Label {
                            text: "<a href='https://github.com/yeeboein/linux-magnify'>Project page</a>"
                            onLinkActivated: link => Qt.openUrlExternally(link)
                        }
                        Label {
                            Layout.fillWidth: true; wrapMode: Text.WordWrap; opacity: 0.65
                            text: "Config file: " + (root.cfg.config_path || "")
                                  + "\nCommands: linux-magnify, linux-magnify --settings, --menu, --update, --disable (magdoc works too)"
                        }
                    }
                }
            }
        }

        // ------------------------------------------------------------- add app
        Popup {
            id: addPopup
            anchors.centerIn: parent
            width: 440
            height: 520
            modal: true
            onOpened: { appSearch.text = ""; appSearch.forceActiveFocus(); }

            ColumnLayout {
                anchors.fill: parent
                spacing: 8
                Label { text: "Add App"; font.pixelSize: 16; font.bold: true }
                TextField {
                    id: appSearch
                    Layout.fillWidth: true
                    placeholderText: "Search apps"
                    onTextChanged: root.appQuery = text.toLowerCase()
                }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: root.allApps.filter(a => root.appQuery === "" || a.name.toLowerCase().includes(root.appQuery)
                                                   || a.id.toLowerCase().includes(root.appQuery))
                    ScrollBar.vertical: ScrollBar {}
                    delegate: ItemDelegate {
                        required property var modelData
                        width: ListView.view.width
                        contentItem: RowLayout {
                            spacing: 10
                            Image {
                                width: 28; height: 28
                                sourceSize.width: 56; sourceSize.height: 56
                                source: root.iconSource(modelData.icon, "application-x-executable")
                            }
                            Label { text: modelData.name; Layout.fillWidth: true; elide: Text.ElideRight }
                        }
                        onClicked: { root.addPinned(modelData.id); addPopup.close(); }
                    }
                }
            }
        }
    }
}
