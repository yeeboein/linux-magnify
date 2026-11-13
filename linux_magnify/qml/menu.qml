// Magdoc start menu (Quickshell).
//
// Started in the background by Magdoc. It opens and closes when Magdoc writes
// $XDG_RUNTIME_DIR/magdoc-menu.json, which happens on the dock's home button,
// the Meta key (Plasma) and `magdoc --menu`. The file also says which edge the
// dock is on and how far the menu must stay from it, so the dock never crops it.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    property bool open: false
    property string edge: "bottom"
    property int gap: 140          // distance from the screen edge (clears the magnified icons)
    property int lastSeq: -1
    property string query: ""
    readonly property string python: Quickshell.env("MAGDOC_PYTHON") || "python3"

    readonly property var apps: DesktopEntries.applications.values
        .filter(a => !a.noDisplay && (root.query === ""
            || (a.name + " " + (a.genericName || "") + " " + (a.comment || "")).toLowerCase().includes(root.query)))
        .sort((a, b) => a.name.localeCompare(b.name))

    function handle(text) {
        let d;
        try { d = JSON.parse(text); } catch (e) { return; }
        root.edge = d.edge || "bottom";
        root.gap = d.gap || root.gap;
        const fresh = Date.now() - (d.time || 0) < 4000;
        if (root.lastSeq < 0 && !fresh) { root.lastSeq = d.seq; return; }  // stale trigger at startup
        if (d.seq === root.lastSeq) return;
        root.lastSeq = d.seq;
        if (d.action === "toggle") root.open = !root.open;
        else if (d.action === "open") root.open = true;
        else if (d.action === "close") root.open = false;
    }

    component PowerButton: Button {
        flat: true
        palette.buttonText: "white"
        background: Rectangle {
            radius: 10
            color: parent.hovered ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.06)
        }
    }

    function launch(entry) {
        entry.execute();
        root.open = false;
    }

    function run(cmd) {
        Quickshell.execDetached(cmd);
        root.open = false;
    }

    FileView {
        id: trigger
        path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/magdoc-menu.json"
        watchChanges: true
        onFileChanged: trigger.reload()
        onLoaded: root.handle(trigger.text())
    }

    // Click anywhere outside the menu to close it.
    PanelWindow {
        visible: root.open
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Top
        WlrLayershell.namespace: "magdoc-menu-backdrop"
        MouseArea { anchors.fill: parent; onClicked: root.open = false }
    }

    PanelWindow {
        id: menu
        visible: root.open
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "magdoc-menu"
        WlrLayershell.keyboardFocus: root.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

        anchors {
            bottom: root.edge === "bottom"
            top: root.edge === "top"
            left: root.edge === "left"
            right: root.edge === "right"
        }
        margins {
            bottom: root.edge === "bottom" ? root.gap : 0
            top: root.edge === "top" ? root.gap : 0
            left: root.edge === "left" ? root.gap : 0
            right: root.edge === "right" ? root.gap : 0
        }

        // Sized to fit next to the dock: never taller/wider than the space that's left.
        readonly property int screenW: screen ? screen.width : 1280
        readonly property int screenH: screen ? screen.height : 800
        readonly property bool vertical: root.edge === "left" || root.edge === "right"
        implicitWidth: Math.min(660, screenW - 32 - (vertical ? root.gap : 0))
        implicitHeight: Math.min(560, screenH - 32 - (vertical ? 0 : root.gap))

        onVisibleChanged: if (visible) { search.text = ""; search.forceActiveFocus(); }

        Rectangle {
            anchors.fill: parent
            radius: 20
            color: Qt.rgba(0.11, 0.11, 0.13, 0.94)
            border.color: Qt.rgba(1, 1, 1, 0.12)
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                TextField {
                    id: search
                    Layout.fillWidth: true
                    placeholderText: "Search apps"
                    color: "white"
                    placeholderTextColor: Qt.rgba(1, 1, 1, 0.45)
                    font.pixelSize: 15
                    leftPadding: 14
                    background: Rectangle { radius: 12; color: Qt.rgba(1, 1, 1, 0.08) }
                    onTextChanged: root.query = text.toLowerCase()
                    onAccepted: if (root.apps.length > 0) root.launch(root.apps[0])
                    Keys.onEscapePressed: root.open = false
                    Keys.onDownPressed: grid.forceActiveFocus()
                }

                GridView {
                    id: grid
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: root.apps
                    readonly property int columns: Math.max(1, Math.floor(width / 100))
                    cellWidth: Math.floor(width / columns)
                    cellHeight: 100
                    keyNavigationEnabled: true
                    Keys.onEscapePressed: root.open = false
                    Keys.onReturnPressed: if (currentIndex >= 0) root.launch(root.apps[currentIndex])
                    ScrollBar.vertical: ScrollBar {}

                    delegate: Item {
                        id: cell
                        required property var modelData
                        required property int index
                        width: grid.cellWidth
                        height: grid.cellHeight

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: 4
                            radius: 14
                            color: hover.hovered || (grid.activeFocus && grid.currentIndex === cell.index)
                                   ? Qt.rgba(1, 1, 1, 0.12) : "transparent"
                        }
                        HoverHandler { id: hover }
                        TapHandler { onTapped: root.launch(cell.modelData) }

                        Column {
                            anchors.centerIn: parent
                            spacing: 6
                            Image {
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: 48; height: 48
                                sourceSize.width: 96; sourceSize.height: 96
                                source: Quickshell.iconPath(cell.modelData.icon, "application-x-executable")
                                smooth: true
                            }
                            Text {
                                width: grid.cellWidth - 12
                                text: cell.modelData.name
                                color: "white"
                                font.pixelSize: 12
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    PowerButton {
                        text: "Magdoc Settings"
                        onClicked: root.run([root.python, "-m", "linux_magnify", "--settings"])
                    }
                    Item { Layout.fillWidth: true }
                    PowerButton { text: "Lock"; onClicked: root.run(["loginctl", "lock-session"]) }
                    PowerButton {
                        text: "Log Out"
                        onClicked: root.run(["sh", "-c",
                            "qdbus6 org.kde.Shutdown /Shutdown logout 2>/dev/null"
                            + " || qdbus org.kde.Shutdown /Shutdown logout 2>/dev/null"
                            + " || hyprctl dispatch exit 2>/dev/null"
                            + " || loginctl terminate-session \"$XDG_SESSION_ID\""])
                    }
                    PowerButton { text: "Restart"; onClicked: root.run(["systemctl", "reboot"]) }
                    PowerButton { text: "Shut Down"; onClicked: root.run(["systemctl", "poweroff"]) }
                }
            }
        }
    }
}
