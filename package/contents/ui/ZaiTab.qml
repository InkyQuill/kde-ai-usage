import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: zaiTabRoot
    property Item rootItem

    visible: rootItem.enabledTabs[rootItem.activeTab] === "zai" && !rootItem.showSettings
    Layout.fillWidth: true
    spacing: 14

    function fmt(value) {
        if (value === null || value === undefined)
            return "—";
        if (value >= 1000000)
            return (value / 1000000).toFixed(1) + "M";
        if (value >= 1000)
            return (value / 1000).toFixed(1) + "K";
        return String(value);
    }

    function planTitle() {
        if (rootItem.zaiPlanAvailable && rootItem.zaiLevel !== "") {
            var level = rootItem.zaiLevel;
            return "GLM Coding " + level.charAt(0).toUpperCase() + level.slice(1).toLowerCase();
        }
        return "Z.AI";
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        visible: rootItem.zaiKeyValid

        Kirigami.Icon {
            source: "user-identity"
            width: 14
            height: 14
            color: rootItem.zaiAccent
            isMask: true
            opacity: 0.75
        }

        PlasmaComponents.Label {
            text: zaiTabRoot.planTitle()
            font.pixelSize: 10
            opacity: 0.65
            color: Kirigami.Theme.textColor
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        Rectangle {
            visible: rootItem.zaiTokenSource === "zcode"
            implicitHeight: 18
            implicitWidth: zaiSourceBadgeLabel.implicitWidth + 12
            radius: 4
            color: Qt.rgba(0.54, 0.56, 0.6, 0.18)
            border.width: 1
            border.color: Qt.rgba(0.54, 0.56, 0.6, 0.35)

            PlasmaComponents.Label {
                id: zaiSourceBadgeLabel
                anchors.centerIn: parent
                text: "ZCODE"
                font.pixelSize: 9
                font.bold: true
                color: rootItem.zaiAccent
            }
        }

        Rectangle {
            implicitHeight: 18
            implicitWidth: zaiBadgeLabel.implicitWidth + 12
            radius: 4
            color: Qt.rgba(0.54, 0.56, 0.6, 0.18)
            border.width: 1
            border.color: Qt.rgba(0.54, 0.56, 0.6, 0.35)

            PlasmaComponents.Label {
                id: zaiBadgeLabel
                anchors.centerIn: parent
                text: rootItem.zaiLevel !== "" ? rootItem.zaiLevel.toUpperCase() : "CONNECTED"
                font.pixelSize: 9
                font.bold: true
                color: rootItem.zaiAccent
            }
        }
    }

    ColumnLayout {
        visible: !rootItem.zaiKeyValid && !rootItem.zaiHasKey && rootItem.zaiError === ""
        Layout.fillWidth: true
        spacing: 6

        PlasmaComponents.Label {
            text: i18n("Not connected")
            font.pixelSize: 12
            font.bold: true
            color: Kirigami.Theme.textColor
            opacity: 0.7
        }

        PlasmaComponents.Label {
            text: "Set a Z.AI token in settings, via\n$ZAI_TOKEN / $Z_AI_API_KEY / ~/.config/zai/token,\nor log in with the ZCode app for coding-plan limits"
            font.pixelSize: 10
            opacity: 0.5
            color: Kirigami.Theme.textColor
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    ColumnLayout {
        visible: rootItem.zaiError !== "" && !rootItem.zaiKeyValid
        Layout.fillWidth: true
        spacing: 6

        PlasmaComponents.Label {
            text: i18n("Z.AI error")
            font.pixelSize: 12
            font.bold: true
            color: "#ef4444"
        }

        PlasmaComponents.Label {
            text: rootItem.errorText(rootItem.zaiError)
            font.pixelSize: 10
            opacity: 0.7
            color: Kirigami.Theme.textColor
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    // ── Coding-plan credit windows (like Codex 5h / weekly) ──────────────────
    ColumnLayout {
        visible: rootItem.zaiKeyValid && rootItem.zaiPlanAvailable
        Layout.fillWidth: true
        spacing: 8

        PopupRow {
            visible: rootItem.zaiSessionAvailable
            label: "5 Hours"
            value: rootItem.zaiSessionPct
            barColor: rootItem.zaiAccent
            countdownText: rootItem.zaiSessionCountdown !== "" ? "in " + rootItem.zaiSessionCountdown : ""
            etaText: rootItem.etaToFull("zs", rootItem.zaiSessionPct)
            deltaText: rootItem.periodDelta("zs", rootItem.zaiSessionPct, 5 * 3600000, "last 5h")
            tokenText: rootItem.zaiSessionUsed !== null && rootItem.zaiSessionTotal !== null && rootItem.zaiSessionTotal > 0 ? zaiTabRoot.fmt(rootItem.zaiSessionUsed) + " / " + zaiTabRoot.fmt(rootItem.zaiSessionTotal) + " credits" : Math.round(100 - rootItem.zaiSessionPct) + "% of credits left"
            tooltipText: "Z.AI coding plan 5-hour limit\nUsed: " + Math.round(rootItem.zaiSessionPct) + "%  ·  " + Math.round(100 - rootItem.zaiSessionPct) + "% left"
        }

        PopupRow {
            visible: rootItem.zaiWeeklyAvailable
            label: "Weekly"
            value: rootItem.zaiWeeklyPct
            barColor: rootItem.zaiAccent
            countdownText: rootItem.zaiWeeklyCountdown !== "" ? "in " + rootItem.zaiWeeklyCountdown : ""
            etaText: rootItem.etaToFull("zw", rootItem.zaiWeeklyPct)
            deltaText: rootItem.periodDelta("zw", rootItem.zaiWeeklyPct, 7 * 24 * 3600000, "last week")
            tokenText: rootItem.zaiWeeklyUsed !== null && rootItem.zaiWeeklyTotal !== null && rootItem.zaiWeeklyTotal > 0 ? zaiTabRoot.fmt(rootItem.zaiWeeklyUsed) + " / " + zaiTabRoot.fmt(rootItem.zaiWeeklyTotal) + " credits" : Math.round(100 - rootItem.zaiWeeklyPct) + "% of credits left"
            tooltipText: "Z.AI coding plan weekly limit\nUsed: " + Math.round(rootItem.zaiWeeklyPct) + "%  ·  " + Math.round(100 - rootItem.zaiWeeklyPct) + "% left"
        }
    }

    // ── Free ZCode Start Plan token buckets ──────────────────────────────────
    ColumnLayout {
        visible: rootItem.zaiKeyValid && rootItem.zaiStartPlanBalances.length > 0
        Layout.fillWidth: true
        spacing: 8

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Qt.rgba(1, 1, 1, 0.08)
        }

        PlasmaComponents.Label {
            text: rootItem.zaiStartPlanName !== "" ? rootItem.zaiStartPlanName : "Start Plan"
            font.pixelSize: 11
            font.bold: true
            opacity: 0.7
            color: Kirigami.Theme.textColor
        }

        Repeater {
            model: rootItem.zaiStartPlanBalances

            PopupRow {
                label: modelData.model || "model"
                value: modelData.total > 0 ? Math.min(100, (modelData.used / modelData.total) * 100) : 0
                barColor: rootItem.zaiAccent
                countdownText: {
                    var cd = rootItem.formatCountdown(rootItem.dateFromEpoch(modelData.resetAt));
                    return cd === "resetting..." ? "resetting..." : (cd !== "" ? "in " + cd : "");
                }
                tokenText: zaiTabRoot.fmt(modelData.used) + " / " + zaiTabRoot.fmt(modelData.total) + " tokens"
                tooltipText: (modelData.model || "model") + " daily token bucket\nResets daily"
            }
        }
    }

    // ── Legacy API-token quotas (shown when no coding-plan windows) ──────────
    ColumnLayout {
        visible: rootItem.zaiKeyValid && !rootItem.zaiPlanAvailable
        Layout.fillWidth: true
        spacing: 8

        PopupRow {
            label: i18n("5h Tokens")
            value: rootItem.zaiTokenPct
            barColor: rootItem.zaiAccent
            countdownText: rootItem.zaiTokenCountdown !== "" ? i18n("in %1", rootItem.zaiTokenCountdown) : ""
            tokenText: rootItem.zaiTokenUsed === null || rootItem.zaiTokenLimit === null ? "—" : zaiTabRoot.fmt(rootItem.zaiTokenUsed) + " / " + zaiTabRoot.fmt(rootItem.zaiTokenLimit)
            tooltipText: i18n("Z.AI token quota") + (rootItem.zaiTokenCountdown !== "" ? "\n" + i18n("Resets in %1", rootItem.zaiTokenCountdown) : "")
        }

        PopupRow {
            label: i18n("Monthly Tools")
            value: rootItem.zaiToolsPct
            barColor: rootItem.zaiAccent
            countdownText: rootItem.zaiToolsCountdown !== "" ? i18n("in %1", rootItem.zaiToolsCountdown) : ""
            tokenText: rootItem.zaiToolsRemaining !== null ? i18n("%1 remaining", zaiTabRoot.fmt(rootItem.zaiToolsRemaining)) : "—"
            tooltipText: i18n("Z.AI monthly tool quota") + (rootItem.zaiToolsCountdown !== "" ? "\n" + i18n("Resets in %1", rootItem.zaiToolsCountdown) : "")
        }

        Rectangle {
            visible: rootItem.zaiModels.length > 0
            Layout.fillWidth: true
            height: zaiModelsCol.implicitHeight + 20
            radius: 8
            color: Qt.rgba(0.54, 0.56, 0.6, 0.08)
            border.width: 1
            border.color: Qt.rgba(0.54, 0.56, 0.6, 0.22)

            ColumnLayout {
                id: zaiModelsCol
                anchors {
                    left: parent.left
                    right: parent.right
                    top: parent.top
                    margins: 10
                }
                spacing: 6

                PlasmaComponents.Label {
                    text: i18n("Model usage")
                    font.pixelSize: 11
                    font.bold: true
                    opacity: 0.75
                    color: Kirigami.Theme.textColor
                }

                Repeater {
                    model: rootItem.zaiModels.slice(0, 5)

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        PlasmaComponents.Label {
                            text: modelData.modelCode || i18n("unknown")
                            font.pixelSize: 10
                            color: Kirigami.Theme.textColor
                            opacity: 0.7
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }

                        PlasmaComponents.Label {
                            text: zaiTabRoot.fmt(modelData.usage)
                            font.pixelSize: 10
                            font.bold: true
                            color: rootItem.zaiAccent
                        }
                    }
                }
            }
        }
    }
}
