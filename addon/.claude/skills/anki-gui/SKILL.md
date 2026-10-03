---
name: anki-gui
description: Build or modify Anki add-on GUIs (dialogs, menus, widgets, webviews) with PyQt6 via aqt.qt. Use for any Anki add-on UI work or when you need to find the right PyQt6 class.
---

# Anki GUI (PyQt6 via aqt.qt)

> **Klaus override (this repo):** app-modal `exec()` is banned in klaus_note (K-114, completed by K-125). Open every dialog window-modal with `open()` or `show()` and read results from signals (`finished`, `accepted`, `textValueSelected`, and so on). The helpers that exec internally are banned too: `askUser`, `askUserDialog`, `getText`, `getOnlyText`, `chooseList`, static `QInputDialog.getX`, `QMessageBox.question`. `QMenu.exec` is fine. Ban pins live in `tests/test_bridge_reentrancy.py` and `tests/test_drive.py`. Where rules 5 and 6 below say otherwise, this note wins. See also the `anki-qt-dev` skill.

Use this skill when writing or fixing the user-facing part of an Anki add-on: menu actions, dialogs, config windows, custom widgets, webview tweaks, or background work that updates the UI. For talking to a running Anki over HTTP (AnkiConnect), use the anki-connect skill instead.

Part 1 is Anki-specific rules. Part 2 is the complete PyQt6 6.11 class index (every class, grouped by module) so you can pick the right class without guessing.

Sources for Part 1:

- Qt and PyQt: https://addon-docs.ankiweb.net/qt.html
- A basic add-on: https://addon-docs.ankiweb.net/a-basic-addon.html
- Background ops: https://addon-docs.ankiweb.net/background-ops.html
- Hooks and filters: https://addon-docs.ankiweb.net/hooks-and-filters.html
- Porting tips for 23.10 (Qt5 compat removal, enums): https://forums.ankiweb.net/t/porting-tips-for-anki-23-10/35916
- 2.1.50 changes (Qt6, resource URLs): https://changes.ankiweb.net/changes/2.1.50-59.html
- aqt.qt source: https://github.com/ankitects/anki/blob/main/qt/aqt/qt/__init__.py and https://github.com/ankitects/anki/blob/main/qt/aqt/qt/qt6.py
- aqt.utils source: https://github.com/ankitects/anki/blob/main/qt/aqt/utils.py
- PyQt6 class index (Part 2): https://www.riverbankcomputing.com/static/Docs/PyQt6/sip-classes.html

These were checked on 2026-09-30. Anki's source changes over time; if a name below fails, read the current source before assuming.

## Part 1: Anki rules

### 1. Import from aqt.qt, not PyQt6

```python
from aqt import mw
from aqt.qt import *          # Qt classes, pyqtSignal, sip, qconnect, qtmajor/qtminor
from aqt.utils import showInfo, tooltip, askUser, qconnect
```

What `aqt.qt` actually re-exports (from `qt6.py`):

- `PyQt6.sip`
- everything in `QtCore`, `QtGui`, `QtWidgets`, `QtQuick`, `QtWebEngineCore`, `QtWebEngineWidgets`
- only `QLocalServer`, `QLocalSocket`, `QNetworkProxy` from `QtNetwork`
- only `QWebChannel` from `QtWebChannel`

Anything else in Part 2 (QtMultimedia, QtSvg, QtCharts, QtSql, QtPdf, QtPrintSupport, other QtNetwork classes, etc.) is NOT in `aqt.qt`. Import it from `PyQt6.<Module>` directly, and guard the import, because it is not confirmed that every module is shipped in Anki's bundled PyQt6:

```python
try:
    from PyQt6.QtMultimedia import QMediaPlayer
except ImportError:
    QMediaPlayer = None  # degrade gracefully
```

`aqt.qt` also defines `qtmajor`, `qtminor`, `qtpoint`, `qtfullversion` (from `QLibraryInfo.version()`) and raises if Qt is 6.0 or 6.1. Use these for version checks instead of parsing strings.

### 2. Qt6 only; Qt5 habits break

- PyQt5 compat was disabled by default in Anki 23.10 (`ENABLE_QT5_COMPAT=1` was a temporary escape hatch that was announced for removal). Write Qt6 code.
- Enums must be fully scoped: `QFont.StyleHint.Monospace`, not `QFont.Monospace`; `QWizard.WizardStyle.ClassicStyle`; likewise `Qt.AlignmentFlag.AlignLeft`, `QMessageBox.StandardButton.Yes`, `QDialogButtonBox.StandardButton.Ok`, `Qt.ItemDataRole.UserRole`. When unsure of the enum class, open the class page in the PyQt6 docs.
- Use `dialog.exec()`, not `exec_()` (PyQt6 dropped `exec_`; this is a PyQt6 change, verify against your target if in doubt).
- The Qt resource system (pyrcc) is gone in PyQt6. Anki's own icon URLs changed from `:/icons/foo.jpg` to `icons:foo.jpg`. Ship your own icons as files in the add-on folder and load them by path.
- `.ui` files from Qt Designer must be compiled with `pyuic6` for Qt6 (Anki's docs: files generated for PyQt6 do not work with PyQt5 and vice versa).

### 3. Keep references or widgets vanish

A top-level widget created in a function and held only by a local variable is garbage collected when the function returns. Either give it a parent or store it on a long-lived object:

```python
def open_panel() -> None:
    mw.my_panel = panel = MyPanel(mw)   # parent + reference
    panel.show()
```

### 4. Minimal menu action (from the official basic add-on)

```python
from aqt import mw
from aqt.utils import showInfo, qconnect
from aqt.qt import *

def test_function() -> None:
    showInfo(f"Card count: {mw.col.card_count()}")

action = QAction("test", mw)
qconnect(action.triggered, test_function)
mw.form.menuTools.addAction(action)
```

`qconnect(signal, func)` is just `signal.connect(func)` wrapped so type checkers stop complaining.

### 5. Dialog skeleton

```python
from aqt import mw
from aqt.qt import *
from aqt.utils import restoreGeom, saveGeom, disable_help_button

class MyDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent or mw)
        self.setWindowTitle("My Add-on")
        disable_help_button(self)

        self.name = QLineEdit()
        self.enabled = QCheckBox("Enabled")
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow(self.enabled)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        qconnect(buttons.accepted, self.accept)
        qconnect(buttons.rejected, self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        restoreGeom(self, "myaddon_dialog")

    def done(self, r: int) -> None:
        saveGeom(self, "myaddon_dialog")
        super().done(r)
```

Use `dlg.show()` for non-modal (keep a reference, rule 3) or `dlg.exec()` for modal.

### 6. aqt.utils helpers worth knowing

Message and input: `showInfo`, `showWarning`, `showCritical`, `showText`, `askUser`, `askUserDialog`, `getText`, `getOnlyText`, `chooseList`, `tooltip(msg, period=3000)`, `closeTooltip`, plus newer non-blocking `show_info`, `show_warning`, `show_critical`, `ask_user(text, callback)`, `ask_user_dialog`. Files: `getFile`, `getSaveFile`, `openFolder`, `show_in_folder`, `openLink`. Persisting UI state (keyed per profile): `saveGeom`/`restoreGeom`, `saveState`/`restoreState` (QMainWindow, QFileDialog), `saveSplitter`/`restoreSplitter`, `saveHeader`/`restoreHeader`, `save_is_checked`/`restore_is_checked`, `save_combo_history`/`restore_combo_history`. Misc: `disable_help_button`, `setWindowIcon`, `current_window`, `add_ellipsis_to_action_label`, `ensure_editor_saved`, `skip_if_selection_is_empty`, `no_arg_trigger`.

Signatures change between Anki versions. Check `qt/aqt/utils.py` for the version you target.

### 7. Never touch Qt from a background thread

Long work on the main thread freezes Anki. Use Anki's ops, and follow the three rules from the docs: read widget values before starting, update UI only in `success`, and use `mw.taskman.run_on_main` for mid-run updates.

```python
from aqt.operations import QueryOp

def work(col) -> int:          # background thread: NO Qt calls here
    return len(col.find_notes("tag:todo"))

def done(count: int) -> None:  # main thread
    tooltip(f"{count} notes")

QueryOp(parent=mw, op=work, success=done).with_progress().run_in_background()
```

- `QueryOp` for read-only or non-undoable work. Add `.without_collection()` if it does not touch the collection, so it does not queue behind collection ops.
- `CollectionOp` (and helpers in `aqt.operations.*`, e.g. `remove_notes(parent=mw, note_ids=ids).run_in_background()`) for undoable collection changes.
- Progress from inside the loop:

```python
mw.taskman.run_on_main(
    lambda: mw.progress.update(label=f"Remaining: {left}", value=total - left, max=total)
)
```

### 8. Hooks instead of monkey-patching

```python
from aqt import gui_hooks
gui_hooks.reviewer_did_show_question.append(my_func)
```

Many add-ons can register on the same hook; remove with `.remove()`. Webview hooks: `webview_will_set_content` (inject CSS/JS/HTML), `webview_did_receive_js_message` (handle `pycmd(...)` from JS), `webview_did_inject_style_into_page`. Serve add-on web files with `mw.addonManager.setWebExports(__name__, r"web/.*(css|js)")` and reference them under `/_addons/<addon folder>/web/...`. Full hook list: `qt/tools/genhooks_gui.py` in the Anki repo.

### 9. Picking a class

1. Search Part 2 for the job (e.g. "list", "tree", "table", "splitter", "completer", "validator", "clipboard", "shortcut", "drag").
2. Prefer QtWidgets/QtGui/QtCore classes: they are in `aqt.qt` and match Anki's look.
3. Open the docs page: `https://www.riverbankcomputing.com/static/Docs/PyQt6/api/<module lowercase>/<class lowercase>.html` (example: `.../api/qtwidgets/qlistwidget.html`). Nested classes use a hyphen: `.../api/qtgui/qinputmethodevent-attribute.html`.
4. Skip QtQuick/QML, Qt3D*, QtDataVisualization, QtGraphs, QtSensors, QtBluetooth, QtNfc, QtPositioning, QAxContainer, QtDesigner for normal add-ons. They exist but are the wrong tool for Anki's widget UI.

Common picks for Anki add-ons:

- Windows: QDialog, QMainWindow, QDockWidget (attach to `mw`), QWidget
- Layout: QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QSplitter, QScrollArea, QTabWidget, QStackedWidget, QGroupBox
- Inputs: QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QRadioButton, QComboBox, QSlider, QKeySequenceEdit, QCompleter
- Lists and tables: QListWidget, QTreeWidget, QTableWidget (simple); QListView/QTreeView/QTableView + QAbstractTableModel/QStandardItemModel + QSortFilterProxyModel (large data)
- Actions and menus: QAction, QMenu, QShortcut, QKeySequence, QActionGroup, QToolButton
- Feedback: QProgressBar, QLabel, QToolTip, QMessageBox (prefer aqt.utils wrappers)
- Web: QWebEngineView/QWebEnginePage exist, but inside Anki use `aqt.webview.AnkiWebView` for consistency (Anki-specific, check the source for its API)
- Timing: QTimer (`mw.progress.timer(...)` is Anki's wrapper; confirm signature in `aqt/progress.py`)
- Files/paths: QFileDialog (or aqt.utils getFile), QDesktopServices.openUrl, QUrl
- Clipboard: QGuiApplication.clipboard() / QApplication.clipboard()

## Part 2: Complete PyQt6 6.11 class index

Source: https://www.riverbankcomputing.com/static/Docs/PyQt6/sip-classes.html (1,446 entries, copied 2026-09-30). Format: `- Class: description`. Nested classes are written `Outer.Inner`. Where the docs only say "TODO", just the name is listed. Modules are ordered roughly by usefulness for Anki. Fully in `aqt.qt`: QtCore, QtGui, QtWidgets, QtWebEngineCore, QtWebEngineWidgets, QtQuick. Partly: QtNetwork (only QLocalServer, QLocalSocket, QNetworkProxy) and QtWebChannel (only QWebChannel). Everything else needs a direct, guarded `PyQt6.<Module>` import (rule 1).

### QtCore (178)

- QAbstractAnimation: The base of all animations
- QAbstractEventDispatcher: Interface to manage Qt's event queue
- QAbstractItemModel: The abstract interface for item model classes
- QAbstractListModel: Abstract model that can be subclassed to create one-dimensional list models
- QAbstractNativeEventFilter: Interface for receiving native events, such as MSG or XCB event structs
- QAbstractProxyModel: Base class for proxy item models that can do sorting, filtering or other data processing tasks
- QAbstractTableModel: Abstract model that can be subclassed to create table models
- QAnimationGroup: Abstract base class for groups of animations
- QBasicTimer: Timer events for objects
- QBitArray: Array of bits
- QBluetoothPermission: Access Bluetooth peripherals
- QBuffer: QIODevice interface for a QByteArray
- QByteArray: Array of bytes
- QByteArrayMatcher: Holds a sequence of bytes that can be quickly matched in a byte array
- QCalendar: Describes calendar systems
- QCalendarPermission: Access the user's calendar
- QCameraPermission: Access the camera for taking pictures or videos
- QCborError
- QCborStreamReader: Simple CBOR stream decoder, operating on either a QByteArray or QIODevice
- QCborStreamWriter: Simple CBOR encoder operating on a one-way stream
- QChar: 16-bit Unicode character
- QChildEvent: Contains event parameters for child object events
- QCollator: Compares strings according to a localized collation algorithm
- QCollatorSortKey: Can be used to speed up string collation
- QCommandLineOption: Defines a possible command-line option
- QCommandLineParser: Means for handling the command line options
- QConcatenateTablesProxyModel: Proxies multiple source models, concatenating their rows
- QMetaObject.Connection
- QContactsPermission: Access the user's contacts
- QCoreApplication: Event loop for Qt applications without UI
- QCryptographicHash: Way to generate cryptographic hashes
- QDataStream: Serialization of binary data to a QIODevice
- QDate: Date functions
- QDateTime: Date and time functions
- QDeadlineTimer: Marks a deadline in the future
- QDir: Access to directory structures and their contents
- QDirIterator: Iterator for directory entrylists
- QDynamicPropertyChangeEvent: Contains event parameters for dynamic property change events
- QEasingCurve: Easing curves for controlling animation
- QElapsedTimer: Fast way to calculate elapsed times
- QEvent: The base class of all event classes. Event objects contain event parameters
- QEventLoop: Means of entering and leaving an event loop
- QEventLoopLocker: Means to quit an event loop when it is no longer needed
- QFile: Interface for reading from and writing to files
- QFileDevice: Interface for reading from and writing to open files
- QFileInfo: OS-independent API to retrieve information about file system entries
- QFileSelector: Convenient way of selecting file variants
- QFileSystemWatcher: Interface for monitoring files and directories for modifications
- QByteArray.FromBase64Result: QByteArray::FromBase64Result class holds the result of a call to QByteArray::fromBase64Encoding
- QGenericArgument: Internal helper class for marshalling arguments
- QGenericReturnArgument: Internal helper class for marshalling arguments
- QUuid.Id128Bytes
- QIdentityProxyModel: Proxies its source model unmodified
- QIODevice: The base interface class of all I/O devices in Qt
- QIODeviceBase
- QItemSelection: Manages information about selected items in a model
- QItemSelectionModel: Keeps track of a view's selected items
- QItemSelectionRange: Manages information about a range of selected items in a model
- QJsonDocument: Way to read and write JSON documents
- QJsonParseError
- QJsonValue: Encapsulates a value in JSON
- QKeyCombination: Stores a combination of a key with optional modifiers
- QLibrary: Loads shared libraries at runtime
- QLibraryInfo: Information about the Qt library
- QLine: Two-dimensional vector using integer precision
- QLineF: Two-dimensional vector using floating point precision
- QLocale: Converts between numbers and their string representations in various languages
- QLocationPermission: Access the user's location
- QLockFile: Locking between processes using a file
- QLoggingCategory: Represents a category, or 'area' in the logging infrastructure
- QMargins: Defines the four margins of a rectangle
- QMarginsF: Defines the four margins of a rectangle
- QMessageAuthenticationCode: Way to generate hash-based message authentication codes
- QMessageLogContext: Additional information about a log message
- QMessageLogger: Generates log messages
- QMetaClassInfo: Additional information about a class
- QMetaEnum: Meta-data about an enumerator
- QMetaMethod: Meta-data about a member function
- QMetaObject
- QMetaProperty: Meta-data about a property
- QMetaType: Manages named types in the meta-object system
- QMicrophonePermission: Access the microphone for monitoring or recording sound
- QMimeData: Container for data that records information about its MIME type
- QMimeDatabase: Maintains a database of MIME types
- QMimeType: Describes types of file or data, represented by a MIME type string
- QModelIndex: Used to locate data in a data model
- QModelRoleData: Holds a role and the data associated to that role
- QModelRoleDataSpan: Span over QModelRoleData objects
- QMutex: Access serialization between threads
- QMutexLocker
- QNativeInterface
- QNativeIpcKey: Holds a native key used by QSystemSemaphore and QSharedMemory
- QObject: The base class of all Qt objects
- QObjectCleanupHandler: Watches the lifetime of multiple QObjects
- QTimeZone.OffsetData
- QOperatingSystemVersion: Information about the operating system version
- QOperatingSystemVersionBase
- QParallelAnimationGroup: Parallel group of animations
- QPauseAnimation: Pause for QSequentialAnimationGroup
- QPermission: An opaque wrapper of a typed permission
- QPersistentModelIndex: Used to locate data in a data model
- QPluginLoader: Loads a plugin at run-time
- QPoint: Defines a point in the plane using integer precision
- QPointF: Defines a point in the plane using floating point precision
- QProcess: Used to start external programs and to communicate with them
- QProcessEnvironment: Holds the environment variables that can be passed to a program
- QPropertyAnimation: Animates Qt properties
- QPyAbstractRange: The abstract base class for Python ranges
- QPySequenceRange: Encapsulate a Python object as a sequence range
- QPyTableRange: Encapsulate a Python object as a table range
- QRandomGenerator: Allows one to obtain random values from a high-quality Random Number Generator
- QRangeModel: Implements QAbstractItemModel for a Python range
- QReadLocker: Convenience class that simplifies locking and unlocking read-write locks for read access
- QReadWriteLock: Read-write locking
- QRect: Defines a rectangle in the plane using integer precision
- QRectF: Defines a finite rectangle in the plane using floating point precision
- QRecursiveMutex: Access serialization between threads
- QRegularExpression: Pattern matching using regular expressions
- QRegularExpressionMatch: The results of a matching a QRegularExpression against a string
- QRegularExpressionMatchIterator: Iterator on the results of a global match of a QRegularExpression object against a string
- QResource: Interface for reading directly from resources
- QRunnable: The base class for all runnable objects
- QSaveFile: Interface for safely writing to files
- QSemaphore: General counting semaphore
- QSemaphoreReleaser: Exception-safe deferral of a QSemaphore::release() call
- QSequentialAnimationGroup: Sequential group of animations
- QSettings: Persistent platform-independent application settings
- QSharedMemory: Access to a shared memory segment
- QSignalBlocker: Exception-safe wrapper around QObject::blockSignals()
- QSignalMapper: Bundles signals from identifiable senders
- QSize: Defines the size of a two-dimensional object using integer point precision
- QSizeF: Defines the size of a two-dimensional object using floating point precision
- QSocketNotifier: Support for monitoring activity on a file descriptor
- QSortFilterProxyModel: Support for sorting and filtering data passed between another model and a view
- QStandardPaths: Methods for accessing standard paths
- QStorageInfo: Provides information about currently mounted storage and drives
- QStringConverter: Base class for encoding and decoding text
- QStringConverterBase
- QStringDecoder: State-based decoder for text
- QStringEncoder: State-based encoder for text
- QStringListModel: Model that supplies strings to views
- QSysInfo: Information about the system
- QSystemSemaphore: General counting system semaphore
- Qt
- QTemporaryDir: Creates a unique directory for temporary use
- QTemporaryFile: I/O device that operates on temporary files
- QTextBoundaryFinder: Way of finding Unicode text boundaries in a string
- QTextStream: Convenient interface for reading and writing text
- QThread: Platform-independent way to manage threads
- QThreadPool: Manages a collection of QThreads
- QTime: Clock time functions
- QTimeLine: Timeline for controlling animations
- QTimer: Repetitive and single-shot timers
- QTimerEvent: Contains parameters that describe a timer event
- QAbstractEventDispatcher.TimerInfo
- QTimeZone: Identifies how a time representation relates to UTC
- QTranslator: Internationalization support for text output
- QTransposeProxyModel: This proxy transposes the source model
- QTypeRevision: Contains a lightweight representation of a version number with two 8-bit segments, major and minor, either of which can be unknown
- QProcess.UnixProcessParameters
- QUrl: Convenient interface for working with URLs
- QUrlQuery: Way to manipulate a key-value pairs in a URL's query
- QUuid: Stores a Universally Unique Identifier (UUID)
- QVariant: Acts like a union for the most common Qt data types
- QVariantAnimation: Base class for animations
- QVersionNumber: Contains a version number with an arbitrary number of segments
- QWaitCondition: Condition variable for synchronizing threads
- QWinEventNotifier: Support for the Windows Wait functions
- QWriteLocker: Convenience class that simplifies locking and unlocking read-write locks for write access
- QXmlStreamAttribute: Represents a single XML attribute
- QXmlStreamAttributes: Represents a vector of QXmlStreamAttribute
- QXmlStreamEntityDeclaration: Represents a DTD entity declaration
- QXmlStreamEntityResolver: Entity resolver for a QXmlStreamReader
- QXmlStreamNamespaceDeclaration: Represents a namespace declaration
- QXmlStreamNotationDeclaration: Represents a DTD notation declaration
- QXmlStreamReader: Fast parser for reading well-formed XML 1.0 documents via a simple streaming API
- QXmlStreamWriter: XML 1.0 writer with a simple streaming API
- QCalendar.YearMonthDay

### QtGui (192)

- QAbstractFileIconProvider: File icons for the QFileSystemModel class
- QAbstractTextDocumentLayout: Abstract base class used to implement custom layouts for QTextDocuments
- QAccessibilityHints: Contains platform specific accessibility hints and settings
- QAction: Abstraction for user commands that can be added to different user interface components
- QActionEvent: Event that is generated when a QAction is added, removed, or changed
- QActionGroup: Groups actions together
- QInputMethodEvent.Attribute: QInputMethodEvent::Attribute class stores an input method attribute
- QQuaternion.Axes
- QQuaternion.Axis
- QBackingStore: Drawing area for QWindow
- QBitmap: Monochrome (1-bit depth) pixmaps
- QBrush: Defines the fill pattern of shapes drawn by QPainter
- QChildWindowEvent: Contains event parameters for child window changes
- QClipboard: Access to the window system clipboard
- QCloseEvent: Contains parameters that describe a close event
- QColor: Colors based on RGB, HSV or CMYK values
- QColorConstants
- QColorSpace: Color space abstraction
- QColorTransform: Transformation between color spaces
- QConicalGradient: Used in combination with QBrush to specify a conical gradient brush
- QContextMenuEvent: Contains parameters that describe a context menu event
- QCursor: Mouse cursor with an arbitrary shape
- QDesktopServices: Methods for accessing common desktop services
- QDoubleValidator: Range checking of floating-point numbers
- QDrag: Support for MIME-based drag and drop data transfer
- QDragEnterEvent: Event which is sent to a widget when a drag and drop action enters it
- QDragLeaveEvent: Event that is sent to a widget when a drag and drop action leaves it
- QDragMoveEvent: Event which is sent while a drag and drop action is in progress
- QDropEvent: Event which is sent when a drag and drop action is completed
- QPainterPath.Element: QPainterPath::Element class specifies the position and type of a subpath
- QEnterEvent: Contains parameters that describe an enter event
- QEventPoint: Information about a point in a QPointerEvent
- QExposeEvent: Contains event parameters for expose events
- QFileOpenEvent: Event that will be sent when there is a request to open a file or a URL
- QFileSystemModel: Data model for the local filesystem
- QFocusEvent: Contains event parameters for widget focus events
- QFont: Specifies a query for a font used for drawing text
- QFontDatabase: Information about the fonts available in the underlying window system
- QFontInfo: General information about fonts
- QFontMetrics: Font metrics information
- QFontMetricsF: Font metrics information
- QFontVariableAxis: Represents a variable axis in a font
- QTextLayout.FormatRange
- QGlyphRun: Direct access to the internal glyphs in a font
- QGradient: Used in combination with QBrush to specify gradient fills
- QGuiApplication: Manages the GUI application's control flow and main settings
- QHelpEvent: Event that is used to request helpful information about a particular point in a widget
- QHideEvent: Event which is sent after a widget is hidden
- QHoverEvent: Contains parameters that describe a mouse event
- QIcon: Scalable icons in different modes and states
- QIconDragEvent: Indicates that a main icon drag has begun
- QIconEngine: Abstract base class for QIcon renderers
- QImage: Hardware-independent image representation that allows direct access to the pixel data, and can be used as a paint device
- QImageIOHandler: Defines the common image I/O interface for all image formats in Qt
- QImageReader: Format independent interface for reading images from files or other devices
- QImageWriter: Format independent interface for writing images to files or other devices
- QInputDevice: Describes a device from which a QInputEvent originates
- QInputEvent: The base class for events that describe user input
- QInputMethod: Access to the active text input method
- QInputMethodEvent: Parameters for input method events
- QInputMethodQueryEvent: Event sent by the input context to input objects
- QIntValidator: Validator that ensures a string contains a valid integer within a specified range
- QTextBlock.iterator: QTextBlock::iterator class provides an iterator for reading the contents of a QTextBlock
- QTextFrame.iterator: Iterator for reading the contents of a QTextFrame
- QPixmapCache.Key: QPixmapCache::Key class can be used for efficient access to the QPixmapCache
- QKeyEvent: Describes a key event
- QKeySequence: Encapsulates a key sequence as used by shortcuts
- QLinearGradient: Used in combination with QBrush to specify a linear gradient brush
- QMatrix2x2
- QMatrix2x3
- QMatrix2x4
- QMatrix3x2
- QMatrix3x3
- QMatrix3x4
- QMatrix4x2
- QMatrix4x3
- QMatrix4x4: Represents a 4x4 transformation matrix in 3D space
- QMouseEvent: Contains parameters that describe a mouse event
- QMoveEvent: Contains event parameters for move events
- QMovie: Convenience class for playing movies with QImageReader
- QNativeGestureEvent: Contains parameters that describe a gesture event
- QOffscreenSurface: Represents an offscreen surface in the underlying platform
- QOpenGLContext: Represents a native OpenGL context, enabling OpenGL rendering on a QSurface
- QOpenGLContextGroup: Represents a group of contexts sharing OpenGL resources
- QPagedPaintDevice: Represents a paint device that supports multiple pages
- QPageLayout: Describes the size, orientation and margins of a page
- QPageRanges: Represents a collection of page ranges
- QPageSize: Describes the size and name of a defined page size
- QAbstractTextDocumentLayout.PaintContext
- QPaintDevice: The base class of objects that can be painted on with QPainter
- QPaintDeviceWindow: Convenience subclass of QWindow that is also a QPaintDevice
- QPaintEngine: Abstract definition of how QPainter draws to a given device on a given platform
- QPaintEngineState: Information about the active paint engine's current state
- QPainter: Performs low-level painting on widgets and other paint devices
- QPainterPath: Container for painting operations, enabling graphical shapes to be constructed and reused
- QPainterPathStroker: Used to generate fillable outlines for a given painter path
- QPainterStateGuard: RAII convenience class for balanced QPainter::save() and QPainter::restore() calls
- QPaintEvent: Contains event parameters for paint events
- QPalette: Contains color groups for each widget state
- QPdfOutputIntent
- QPdfWriter: Class to generate PDFs that can be used as a paint device
- QPen: Defines how a QPainter should draw lines and outlines of shapes
- QPicture: Paint device that records and replays QPainter commands
- QPixelFormat: Class for describing different pixel layouts in graphics buffers
- QPixmap: Off-screen image representation that can be used as a paint device
- QPixmapCache: Application-wide cache for pixmaps
- QPainter.PixmapFragment: This class is used in conjunction with the QPainter::drawPixmapFragments() function to specify how a pixmap, or sub-rect of a pixmap, is drawn
- QPlatformSurfaceEvent: Used to notify about native platform surface events
- QPointerEvent: A base class for pointer events
- QPointingDevice: Describes a device from which mouse, touch or tablet events originate
- QPointingDeviceUniqueId: Identifies a unique object, such as a tagged token or stylus, which is used with a pointing device
- QPolygon: List of points using integer precision
- QPolygonF: List of points using floating point precision
- QColorSpace.PrimaryPoints
- QQuaternion: Represents a quaternion consisting of a vector and scalar
- QRadialGradient: Used in combination with QBrush to specify a radial gradient brush
- QPageRanges.Range
- QRasterWindow: Convenience class for using QPainter on a QWindow
- QRawFont: Access to a single physical instance of a font
- QRegion: Specifies a clip region for a painter
- QRegularExpressionValidator: Used to check a string against a regular expression
- QResizeEvent: Contains event parameters for resize events
- QRgba64: Struct contains a 64-bit RGB color
- QIconEngine.ScaledPixmapArgument
- QScreen: Used to query screen properties
- QScrollEvent: Sent when scrolling
- QScrollPrepareEvent: Sent in preparation of scrolling
- QAbstractTextDocumentLayout.Selection
- QSessionManager: Access to the session manager
- QShortcut: Used to create keyboard shortcuts
- QShortcutEvent: Event which is generated when the user presses a key combination
- QShowEvent: Event that is sent when a widget is shown
- QSinglePointEvent: A base class for pointer events containing a single point, such as mouse events
- QStandardItem: Item for use with the QStandardItemModel class
- QStandardItemModel: Generic model for storing custom data
- QStaticText: Enables optimized drawing of text when the text and its layout is updated rarely
- QStatusTipEvent: Event that is used to show messages in a status bar
- QStyleHints: Contains platform specific hints and settings
- QSurface: Abstraction of renderable surfaces in Qt
- QSurfaceFormat: Represents the format of a QSurface
- QColorConstants.Svg
- QSyntaxHighlighter: Allows you to define syntax highlighting rules, and in addition you can use the class to query a document's current formatting or user data
- QTextOption.Tab
- QTabletEvent: Contains parameters that describe a Tablet event
- QFont.Tag
- QTextBlock: Container for text fragments in a QTextDocument
- QTextBlockFormat: Formatting information for blocks of text in a QTextDocument
- QTextBlockGroup: Container for text blocks within a QTextDocument
- QTextBlockUserData: Used to associate custom data with blocks of text
- QTextCharFormat: Formatting information for characters in a QTextDocument
- QTextCursor: Offers an API to access and modify QTextDocuments
- QTextDocument: Holds formatted text
- QTextDocumentFragment: Represents a piece of formatted text from a QTextDocument
- QTextDocumentWriter: Format-independent interface for writing a QTextDocument to files or other devices
- QTextFormat: Formatting information for a QTextDocument
- QTextFragment: Holds a piece of text in a QTextDocument with a single QTextCharFormat
- QTextFrame: Represents a frame in a QTextDocument
- QTextFrameFormat: Formatting information for frames in a QTextDocument
- QTextImageFormat: Formatting information for images in a QTextDocument
- QTextInlineObject: Represents an inline object in a QAbstractTextDocumentLayout and its implementations
- QTextItem: All the information required to draw text in a custom paint engine
- QTextLayout: Used to lay out and render text
- QTextLength: Encapsulates the different types of length used in a QTextDocument
- QTextLine: Represents a line of text inside a QTextLayout
- QTextList: Decorated list of items in a QTextDocument
- QTextListFormat: Formatting information for lists in a QTextDocument
- QTextObject: Base class for different kinds of objects that can group parts of a QTextDocument together
- QTextObjectInterface: Allows drawing of custom text objects in QTextDocuments
- QTextOption: Description of general rich text properties
- QTextTable: Represents a table in a QTextDocument
- QTextTableCell: Represents the properties of a cell in a QTextTable
- QTextTableCellFormat: Formatting information for table cells in a QTextDocument
- QTextTableFormat: Formatting information for tables in a QTextDocument
- QTouchEvent: Contains parameters that describe a touch event
- QTransform: Specifies 2D transformations of a coordinate system
- QUndoCommand: The base class of all commands stored on a QUndoStack
- QUndoGroup: Group of QUndoStack objects
- QUndoStack: Stack of QUndoCommand objects
- QUtiMimeConverter: Converts between a MIME type and a Uniform Type Identifier (UTI) format
- QValidator: Validation of input text
- QVector2D: Represents a vector or vertex in 2D space
- QVector3D: Represents a vector or vertex in 3D space
- QVector4D: Represents a vector or vertex in 4D space
- QVulkanExtension
- QVulkanInstance: Represents a native Vulkan instance, enabling Vulkan rendering onto a QSurface
- QVulkanLayer
- QNativeInterface.QWaylandApplication
- QWhatsThisClickedEvent: Event that can be used to handle hyperlinks in a "What's This?" text
- QWheelEvent: Contains parameters that describe a wheel event
- QWindow: Represents a window in the underlying windowing system
- QWindowStateChangeEvent: The window state before a window state change
- QNativeInterface.QX11Application

### QtWidgets (187)

- QAbstractButton: The abstract base class of button widgets, providing functionality common to buttons
- QAbstractGraphicsShapeItem: Common base for all path items
- QAbstractItemDelegate: Used to display and edit data items from a model
- QAbstractItemView: The basic functionality for item view classes
- QAbstractScrollArea: Scrolling area with on-demand scroll bars
- QAbstractSlider: Integer value within a range
- QAbstractSpinBox: Spinbox and a line edit to display values
- QApplication: Manages the GUI application's control flow and main settings
- QBoxLayout: Lines up child widgets horizontally or vertically
- QButtonGroup: Container to organize groups of button widgets
- QCalendarWidget: Monthly based calendar widget allowing the user to select a date
- QCheckBox: Checkbox with a text label
- QColorDialog: Dialog widget for specifying colors
- QColumnView: Model/view implementation of a column view
- QComboBox: Combines a button with a dropdown list
- QCommandLinkButton: Vista style command link button
- QCommonStyle: Encapsulates the common Look and Feel of a GUI
- QCompleter: Completions based on an item model
- QDataWidgetMapper: Mapping between a section of a data model to widgets
- QDateEdit: Widget for editing dates based on the QDateTimeEdit widget
- QDateTimeEdit: Widget for editing dates and times
- QDial: Rounded range control (like a speedometer or potentiometer)
- QDialog: The base class of dialog windows
- QDialogButtonBox: Widget that presents buttons in a layout that is appropriate to the current widget style
- QDockWidget: Widget that can be docked inside a QMainWindow or floated as a top-level window on the desktop
- QDoubleSpinBox: Spin box widget that takes doubles
- QErrorMessage: Error message display dialog
- QTextEdit.ExtraSelection
- QFileDialog: Provides a dialog that allows users to select files or directories
- QFileIconProvider: File icons for the QFileSystemModel class
- QFocusFrame: Focus frame which can be outside of a widget's normal paintable area
- QFontComboBox: Combobox that lets the user select a font family
- QFontDialog: Dialog widget for selecting a font
- QFormLayout: Manages forms of input widgets and their associated labels
- QFrame: The base class of widgets that can have a frame
- QGesture: Represents a gesture, containing properties that describe the corresponding user input
- QGestureEvent: The description of triggered gestures
- QGestureRecognizer: The infrastructure for gesture recognition
- QGraphicsAnchor: Represents an anchor between two items in a QGraphicsAnchorLayout
- QGraphicsAnchorLayout: Layout where one can anchor widgets together in Graphics View
- QGraphicsBlurEffect: Blur effect
- QGraphicsColorizeEffect: Colorize effect
- QGraphicsDropShadowEffect: Drop shadow effect
- QGraphicsEffect: The base class for all graphics effects
- QGraphicsEllipseItem: Ellipse item that you can add to a QGraphicsScene
- QGraphicsGridLayout: Grid layout for managing widgets in Graphics View
- QGraphicsItem: The base class for all graphical items in a QGraphicsScene
- QGraphicsItemGroup: Container that treats a group of items as a single item
- QGraphicsLayout: The base class for all layouts in Graphics View
- QGraphicsLayoutItem: Can be inherited to allow your custom items to be managed by layouts
- QGraphicsLinearLayout: Horizontal or vertical layout for managing widgets in Graphics View
- QGraphicsLineItem: Line item that you can add to a QGraphicsScene
- QGraphicsObject: Base class for all graphics items that require signals, slots and properties
- QGraphicsOpacityEffect: Opacity effect
- QGraphicsPathItem: Path item that you can add to a QGraphicsScene
- QGraphicsPixmapItem: Pixmap item that you can add to a QGraphicsScene
- QGraphicsPolygonItem: Polygon item that you can add to a QGraphicsScene
- QGraphicsProxyWidget: Proxy layer for embedding a QWidget in a QGraphicsScene
- QGraphicsRectItem: Rectangle item that you can add to a QGraphicsScene
- QGraphicsRotation: Rotation transformation around a given axis
- QGraphicsScale: Scale transformation
- QGraphicsScene: Surface for managing a large number of 2D graphical items
- QGraphicsSceneContextMenuEvent: Context menu events in the graphics view framework
- QGraphicsSceneDragDropEvent: Events for drag and drop in the graphics view framework
- QGraphicsSceneEvent: Base class for all graphics view related events
- QGraphicsSceneHelpEvent: Events when a tooltip is requested
- QGraphicsSceneHoverEvent: Hover events in the graphics view framework
- QGraphicsSceneMouseEvent: Mouse events in the graphics view framework
- QGraphicsSceneMoveEvent: Events for widget moving in the graphics view framework
- QGraphicsSceneResizeEvent: Events for widget resizing in the graphics view framework
- QGraphicsSceneWheelEvent: Wheel events in the graphics view framework
- QGraphicsSimpleTextItem: Simple text item that you can add to a QGraphicsScene
- QGraphicsTextItem: Text item that you can add to a QGraphicsScene to display formatted text
- QGraphicsTransform: Abstract base class for building advanced transformations on QGraphicsItems
- QGraphicsView: Widget for displaying the contents of a QGraphicsScene
- QGraphicsWidget: The base class for all widget items in a QGraphicsScene
- QGridLayout: Lays out widgets in a grid
- QGroupBox: Group box frame with a title
- QHBoxLayout: Lines up widgets horizontally
- QHeaderView: Header row or header column for item views
- QInputDialog: Simple convenience dialog to get a single value from the user
- QItemDelegate: Display and editing facilities for data items from a model
- QItemEditorCreatorBase: Abstract base class that must be subclassed when implementing new item editor creators
- QItemEditorFactory: Widgets for editing item data in views and delegates
- QKeySequenceEdit: Allows to input a QKeySequence
- QLabel: Text or image display
- QLayout: The base class of geometry managers
- QLayoutItem: Abstract item that a QLayout manipulates
- QLCDNumber: Displays a number with LCD-like digits
- QLineEdit: One-line text editor
- QListView: List or icon view onto a model
- QListWidget: Item-based list widget
- QListWidgetItem: Item for use with the QListWidget item view class
- QMainWindow: Main application window
- QMdiArea: Area in which MDI windows are displayed
- QMdiSubWindow: Subwindow class for QMdiArea
- QMenu: Menu widget for use in menu bars, context menus, and other popup menus
- QMenuBar: Horizontal menu bar
- QMessageBox: Modal dialog for informing the user or for asking the user a question and receiving an answer
- QPanGesture: Describes a panning gesture made by the user
- QPinchGesture: Describes a pinch gesture made by the user
- QPlainTextDocumentLayout: Implements a plain text layout for QTextDocument
- QPlainTextEdit: Widget that is used to edit and display plain text
- QProgressBar: Horizontal or vertical progress bar
- QProgressDialog: Feedback on the progress of a slow operation
- QProxyStyle: Convenience class that simplifies dynamically overriding QStyle elements
- QPushButton: Command button
- QRadioButton: Radio button with a text label
- QRubberBand: Rectangle or line that can indicate a selection or a boundary
- QScrollArea: Scrolling view onto another widget
- QScrollBar: Vertical or horizontal scroll bar
- QScroller: Enables kinetic scrolling for any scrolling widget or graphics item
- QScrollerProperties: Stores the settings for a QScroller
- QSizeGrip: Resize handle for resizing top-level windows
- QSizePolicy: Layout attribute describing horizontal and vertical resizing policy
- QSlider: Vertical or horizontal slider
- QSpacerItem: Blank space in a layout
- QSpinBox: Spin box widget
- QSplashScreen: Splash screen that can be shown during application startup
- QSplitter: Implements a splitter widget
- QSplitterHandle: Handle functionality for the splitter
- QStackedLayout: Stack of widgets where only one widget is visible at a time
- QStackedWidget: Stack of widgets where only one widget is visible at a time
- QStatusBar: Horizontal bar suitable for presenting status information
- QStyle: Abstract base class that encapsulates the look and feel of a GUI
- QStyledItemDelegate: Display and editing facilities for data items from a model
- QStyleFactory: Creates QStyle objects
- QStyleHintReturn: Style hints that return more than basic data types
- QStyleHintReturnMask: Style hints that return a QRegion
- QStyleHintReturnVariant: Style hints that return a QVariant
- QStyleOption: Stores the parameters used by QStyle functions
- QStyleOptionButton: Used to describe the parameters for drawing buttons
- QStyleOptionComboBox: Used to describe the parameter for drawing a combobox
- QStyleOptionComplex: Used to hold parameters that are common to all complex controls
- QStyleOptionDockWidget: Used to describe the parameters for drawing a dock widget
- QStyleOptionFocusRect: Used to describe the parameters for drawing a focus rectangle with QStyle
- QStyleOptionFrame: Used to describe the parameters for drawing a frame
- QStyleOptionGraphicsItem: Used to describe the parameters needed to draw a QGraphicsItem
- QStyleOptionGroupBox: Describes the parameters for drawing a group box
- QStyleOptionHeader: Used to describe the parameters for drawing a header
- QStyleOptionHeaderV2: Used to describe the parameters for drawing a header
- QStyleOptionMenuItem: Used to describe the parameter necessary for drawing a menu item
- QStyleOptionMenuItemV2: Enhances QStyleOptionMenuItem with new members
- QStyleOptionProgressBar: Used to describe the parameters necessary for drawing a progress bar
- QStyleOptionRubberBand: Used to describe the parameters needed for drawing a rubber band
- QStyleOptionSizeGrip: Used to describe the parameter for drawing a size grip
- QStyleOptionSlider: Used to describe the parameters needed for drawing a slider
- QStyleOptionSpinBox: Used to describe the parameters necessary for drawing a spin box
- QStyleOptionTab: Used to describe the parameters for drawing a tab bar
- QStyleOptionTabBarBase: Used to describe the base of a tab bar, i.e. the part that the tab bar usually overlaps with
- QStyleOptionTabWidgetFrame: Used to describe the parameters for drawing the frame around a tab widget
- QStyleOptionTitleBar: Used to describe the parameters for drawing a title bar
- QStyleOptionToolBar: Used to describe the parameters for drawing a toolbar
- QStyleOptionToolBox: Used to describe the parameters needed for drawing a tool box
- QStyleOptionToolButton: Used to describe the parameters for drawing a tool button
- QStyleOptionViewItem: Used to describe the parameters used to draw an item in a view widget
- QStylePainter: Convenience class for drawing QStyle elements inside a widget
- QSwipeGesture: Describes a swipe gesture made by the user
- QSystemTrayIcon: Icon for an application in the system tray
- QTabBar: Tab bar, e.g. for use in tabbed dialogs
- QTableView: Default model/view implementation of a table view
- QTableWidget: Item-based table view with a default model
- QTableWidgetItem: Item for use with the QTableWidget class
- QTableWidgetSelectionRange: Way to interact with selection in a model without using model indexes and a selection model
- QTabWidget: Stack of tabbed widgets
- QFormLayout.TakeRowResult
- QTapAndHoldGesture: Describes a tap-and-hold (aka LongTap) gesture made by the user
- QTapGesture: Describes a tap gesture made by the user
- QTextBrowser: Rich text browser with hypertext navigation
- QTextEdit: Widget that is used to edit and display both plain and rich text
- QTimeEdit: Widget for editing times based on the QDateTimeEdit widget
- QToolBar: Movable panel that contains a set of controls
- QToolBox: Column of tabbed widget items
- QToolButton: Quick-access button to commands or options, usually used inside a QToolBar
- QToolTip: Tool tips (balloon help) for any widget
- QTreeView: Default model/view implementation of a tree view
- QTreeWidget: Tree view that uses a predefined tree model
- QTreeWidgetItem: Item for use with the QTreeWidget convenience class
- QTreeWidgetItemIterator: Way to iterate over the items in a QTreeWidget instance
- QUndoView: Displays the contents of a QUndoStack
- QVBoxLayout: Lines up widgets vertically
- QWhatsThis: Simple description of any widget, i.e. answering the question "What's This?"
- QWidget: The base class of all user interface objects
- QWidgetAction: Extends QAction by an interface for inserting custom widgets into action based containers, such as toolbars
- QWidgetItem: Layout item that represents a widget
- QWizard: Framework for wizards
- QWizardPage: The base class for wizard pages

### QtWebEngineCore (41)

- QWebEngineGlobalSettings.DnsMode
- QWebEngineCookieStore.FilterRequest
- QWebEngineCertificateError: Information about a certificate error
- QWebEngineClientCertificateSelection: QWebEngineClientCertSelection class wraps a client certificate selection
- QWebEngineClientCertificateStore: In-memory store for client certificates
- QWebEngineClientHints: Object to customize User-Agent Client Hints used by a profile
- QWebEngineContextMenuRequest: Request for populating or extending a context menu with actions
- QWebEngineCookieStore: Access to Chromium's cookies
- QWebEngineDesktopMediaRequest: A request for populating a dialog with available sources for screen capturing
- QWebEngineDownloadRequest: Information about a download
- QWebEngineExtensionInfo: Information about a browser extension
- QWebEngineExtensionManager: Allows applications to install and load Chrome extensions from the filesystem
- QWebEngineFileSystemAccessRequest: Enables accepting or rejecting requests for local file system access from JavaScript applications
- QWebEngineFindTextResult: Encapsulates the result of a string search on a page
- QWebEngineFrame: Gives information about and control over a page frame
- QWebEngineFullScreenRequest: Enables accepting or rejecting requests for entering and exiting the fullscreen mode
- QWebEngineGlobalSettings
- QWebEngineHistory: Represents the history of a web engine page
- QWebEngineHistoryItem: Represents one item in the history of a web engine page
- QWebEngineHistoryModel: A data model that represents the history of a web engine page
- QWebEngineHttpRequest: Holds a request to be sent with WebEngine
- QWebEngineLoadingInfo: A utility type for the WebEngineView::loadingChanged signal
- QWebEngineNavigationRequest: A utility type for the QWebEnginePage::navigationRequested signal
- QWebEngineNewWindowRequest: A utility type for the QWebEnginePage::newWindowRequested() signal
- QWebEngineNotification: Encapsulates the data of an HTML5 web notification
- QWebEnginePage: Object to view and edit web documents
- QWebEnginePermission: A QWebEnginePermission is an object used to access and modify the state of a single permission that's been granted or denied to a specific origin URL
- QWebEngineProfile: Web engine profile shared by multiple pages
- QWebEngineProfileBuilder: Way to construct QWebEngineProfile
- QWebEngineQuotaRequest: Enables accepting or rejecting requests for larger persistent storage than the application's current allocation in File System API
- QWebEngineRegisterProtocolHandlerRequest: Enables accepting or rejecting requests from the registerProtocolHandler API
- QWebEngineScript: Encapsulates a JavaScript program
- QWebEngineScriptCollection: Represents a collection of user scripts
- QWebEngineSettings: Object to store the settings used by QWebEnginePage
- QWebEngineUrlRequestInfo: Information about URL requests
- QWebEngineUrlRequestInterceptor: Abstract base class for URL interception
- QWebEngineUrlRequestJob: Represents a custom URL request
- QWebEngineUrlScheme: Configures a custom URL scheme
- QWebEngineUrlSchemeHandler: Base class for handling custom URL schemes
- QWebEngineWebAuthPinRequest
- QWebEngineWebAuthUxRequest: Encapsulates the data of a WebAuth UX request

### QtWebEngineWidgets (1)

- QWebEngineView: Widget that is used to view and edit web documents

### QtWebChannel (2)

- QWebChannel: Exposes QObjects to remote HTML clients
- QWebChannelAbstractTransport: Communication channel between the C++ QWebChannel server and a HTML/JS client

### QtNetwork (56)

- QAbstractNetworkCache: The interface for cache implementations
- QAbstractSocket: The base functionality common to all socket types
- QAuthenticator: Authentication object
- QDnsDomainNameRecord: Stores information about a domain name record
- QDnsHostAddressRecord: Stores information about a host address record
- QDnsLookup: Represents a DNS lookup
- QDnsMailExchangeRecord: Stores information about a DNS MX record
- QDnsServiceRecord: Stores information about a DNS SRV record
- QDnsTextRecord: Stores information about a DNS TXT record
- QDnsTlsAssociationRecord: Stores information about a DNS TLSA record
- QFormDataBuilder: Convenience class to simplify the construction of QHttpMultiPart objects
- QFormDataPartBuilder: Convenience class to simplify the construction of QHttpPart objects
- QHostAddress: IP address
- QHostInfo: Static functions for host name lookups
- QHstsPolicy: Specifies that a host supports HTTP Strict Transport Security policy (HSTS)
- QHttp1Configuration: Controls HTTP/1 parameters and settings
- QHttp2Configuration: Controls HTTP/2 parameters and settings
- QHttpHeaders: Class for holding HTTP headers
- QHttpMultiPart: Resembles a MIME multipart message to be sent over HTTP
- QHttpPart: Holds a body part to be used inside a HTTP multipart MIME message
- QLocalServer: Local socket based server
- QLocalSocket: Local socket
- QNetworkAccessManager: Allows the application to send network requests and receive replies
- QNetworkAddressEntry: Stores one IP address supported by a network interface, along with its associated netmask and broadcast address
- QNetworkCacheMetaData: Cache information
- QNetworkCookie: Holds one network cookie
- QNetworkCookieJar: Implements a simple jar of QNetworkCookie objects
- QNetworkDatagram: The data and metadata of a UDP datagram
- QNetworkDiskCache: Very basic disk cache
- QNetworkInformation: Exposes various network information through native backends
- QNetworkInterface: Listing of the host's IP addresses and network interfaces
- QNetworkProxy: Network layer proxy
- QNetworkProxyFactory: Fine-grained proxy selection
- QNetworkProxyQuery: Used to query the proxy settings for a socket
- QNetworkReply: Contains the data and headers for a request sent with QNetworkAccessManager
- QNetworkRequest: Holds a request to be sent with QNetworkAccessManager
- QNetworkRequestFactory: Convenience class for grouping remote server endpoints that share common network request properties
- QOcspResponse: This class represents Online Certificate Status Protocol response
- QPasswordDigestor
- QRestAccessManager: Convenience wrapper for QNetworkAccessManager
- QRestReply: Convenience wrapper for QNetworkReply
- QSsl
- QSslCertificate: Convenient API for an X509 certificate
- QSslCertificateExtension: API for accessing the extensions of an X509 certificate
- QSslCipher: Represents an SSL cryptographic cipher
- QSslConfiguration: Holds the configuration and state of an SSL connection
- QSslDiffieHellmanParameters: Interface for Diffie-Hellman parameters for servers
- QSslEllipticCurve: Represents an elliptic curve for use by elliptic-curve cipher algorithms
- QSslError: SSL error
- QSslKey: Interface for private and public keys
- QSslPreSharedKeyAuthenticator: Authentication data for pre shared keys (PSK) ciphersuites
- QSslServer: Implements an encrypted, secure TCP server over TLS
- QSslSocket: SSL encrypted socket for both clients and servers
- QTcpServer: TCP-based server
- QTcpSocket: TCP socket
- QUdpSocket: UDP socket

### QtMultimedia (34)

- QAudio
- QAudioBuffer: Represents a collection of audio samples with a specific format and sample rate
- QAudioBufferInput: Used for providing custom audio buffers to QMediaRecorder through QMediaCaptureSession
- QAudioBufferOutput: Used for capturing audio data provided by QMediaPlayer
- QAudioDecoder: Implements decoding audio
- QAudioDevice: Information about audio devices and their functionality
- QAudioFormat: Stores audio stream parameter information
- QAudioInput: Represents an input channel for audio
- QAudioOutput: Represents an output channel for audio
- QAudioSink: Interface for sending audio data to an audio output device
- QAudioSource: Interface for receiving audio data from an audio input device
- QCamera: Interface for system camera devices
- QCameraDevice: General information about camera devices
- QCameraFormat: Describes a video format supported by a camera device
- QCapturableWindow: Used for getting the basic information of a capturable window
- QImageCapture: Used for the recording of media content
- QMediaTimeRange.Interval
- QMediaCaptureSession: Allows capturing of audio and video content
- QMediaDevices: Information about available multimedia input and output devices
- QMediaFormat: Describes an encoding format for a multimedia file or stream
- QMediaMetaData: Provides meta-data for media files
- QMediaPlayer: Allows the playing of a media files
- QMediaRecorder: Used for encoding and recording a capture session
- QMediaTimeRange: Represents a set of zero or more disjoint time intervals
- QVideoFrame.PaintOptions
- QPlaybackOptions: Enables low-level control of media playback options
- QScreenCapture: This class is used for capturing a screen
- QSoundEffect: Way to play low latency sound effects
- QtVideo
- QVideoFrame: Represents a frame of video data
- QVideoFrameFormat: Specifies the stream format of a video presentation surface
- QVideoFrameInput: Used for providing custom video frames to QMediaRecorder or a video output through QMediaCaptureSession
- QVideoSink: Represents a generic sink for video data
- QWindowCapture: This class is used for capturing a window

### QtMultimediaWidgets (2)

- QGraphicsVideoItem: Graphics item which display video produced by a QMediaPlayer or QCamera
- QVideoWidget: Widget which presents video produced by a media object

### QtSvg (3)

- QtSvg
- QSvgGenerator: Paint device that is used to create SVG drawings
- QSvgRenderer: Used to draw the contents of SVG files onto paint devices

### QtSvgWidgets (2)

- QGraphicsSvgItem: QGraphicsItem that can be used to render the contents of SVG files
- QSvgWidget: Widget that is used to display the contents of Scalable Vector Graphics (SVG) files

### QtPrintSupport (8)

- QAbstractPrintDialog: Base implementation for print dialogs used to configure printers
- QPageSetupDialog: Configuration dialog for the page-related options on a printer
- QPrintDialog: Dialog for specifying the printer's configuration
- QPrintEngine: Defines an interface for how QPrinter interacts with a given printing subsystem
- QPrinter: Paint device that paints on a printer
- QPrinterInfo: Gives access to information about existing printers
- QPrintPreviewDialog: Dialog for previewing and configuring page layouts for printer output
- QPrintPreviewWidget: Widget for previewing page layouts for printer output

### QtPdf (9)

- QPdfBookmarkModel: Holds a tree of links (anchors) within a PDF document, such as the table of contents
- QPdfDocument: Loads a PDF document and renders pages from it
- QPdfDocumentRenderOptions: Holds the options to render a page from a PDF document
- QPdfLink: Defines a link between a region on a page (such as a hyperlink or a search result) and a destination (page, location on the page, and zoom level at which to view it)
- QPdfLinkModel: Holds the geometry and the destination for each link that the specified page contains
- QPdfPageNavigator: Navigation history within a PDF document
- QPdfPageRenderer: Encapsulates the rendering of pages of a PDF document
- QPdfSearchModel: Searches for a string in a PDF document and holds the results
- QPdfSelection: Defines a range of text that has been selected on one page in a PDF document, and its geometric boundaries

### QtPdfWidgets (2)

- QPdfPageSelector: A widget for selecting a PDF page
- QPdfView: A PDF viewer widget

### QtTextToSpeech (2)

- QTextToSpeech: Convenient access to text-to-speech engines
- QVoice: Represents a particular voice

### QtSql (15)

- QSql
- QSqlDatabase: Handles a connection to a database
- QSqlDriver: Abstract base class for accessing specific SQL databases
- QSqlDriverCreatorBase: The base class for SQL driver factories
- QSqlError: SQL database error information
- QSqlField: Manipulates the fields in SQL database tables and views
- QSqlIndex: Functions to manipulate and describe database indexes
- QSqlQuery: Means of executing and manipulating SQL statements
- QSqlQueryModel: Read-only data model for SQL result sets
- QSqlRecord: Encapsulates a database record
- QSqlRelation: Stores information about an SQL foreign key
- QSqlRelationalDelegate: Delegate that is used to display and edit data from a QSqlRelationalTableModel
- QSqlRelationalTableModel: Editable data model for a single database table, with foreign key support
- QSqlResult: Abstract interface for accessing data from specific SQL databases
- QSqlTableModel: Editable data model for a single database table

### QtXml (17)

- QDomAttr: Represents one attribute of a QDomElement
- QDomCDATASection: Represents an XML CDATA section
- QDomCharacterData: Represents a generic string in the DOM
- QDomComment: Represents an XML comment
- QDomDocument: Represents an XML document
- QDomDocumentFragment: Tree of QDomNodes which is not usually a complete QDomDocument
- QDomDocumentType: The representation of the DTD in the document tree
- QDomElement: Represents one element in the DOM tree
- QDomEntity: Represents an XML entity
- QDomEntityReference: Represents an XML entity reference
- QDomImplementation: Information about the features of the DOM implementation
- QDomNamedNodeMap: Contains a collection of nodes that can be accessed by name
- QDomNode: The base class for all the nodes in a DOM tree
- QDomNodeList: List of QDomNode objects
- QDomNotation: Represents an XML notation
- QDomProcessingInstruction: Represents an XML processing instruction
- QDomText: Represents text data in the parsed XML document

### QtTest (3)

- QAbstractItemModelTester: Helps testing QAbstractItemModel subclasses
- QSignalSpy: Enables introspection of signal emission
- QTest

### QtDBus (18)

- QDBus
- QDBusAbstractAdaptor: The base class of D-Bus adaptor classes
- QDBusAbstractInterface: The base class for all D-Bus interfaces in the Qt D-Bus binding, allowing access to remote interfaces
- QDBusArgument: Used to marshall and demarshall D-Bus arguments
- QDBusConnection: Represents a connection to the D-Bus bus daemon
- QDBusConnectionInterface: Access to the D-Bus bus daemon service
- QDBusError: Represents an error received from the D-Bus bus or from remote applications found in the bus
- QDBusInterface: Proxy for interfaces on remote objects
- QDBusMessage: Represents one message sent or received over the D-Bus bus
- QDBusObjectPath: Enables the programmer to identify the OBJECT_PATH type provided by the D-Bus typesystem
- QDBusPendingCall: Refers to one pending asynchronous call
- QDBusPendingCallWatcher: Convenient way for waiting for asynchronous replies
- QDBusPendingReply
- QDBusReply
- QDBusServiceWatcher: Allows the user to watch for a bus service change
- QDBusSignature: Enables the programmer to identify the SIGNATURE type provided by the D-Bus typesystem
- QDBusUnixFileDescriptor: Holds one Unix file descriptor
- QDBusVariant: Enables the programmer to identify the variant type provided by the D-Bus typesystem

### QtOpenGL (22)

- QAbstractOpenGLFunctions: The base class of a family of classes that expose all functions for each OpenGL version and profile
- QOpenGLVertexArrayObject.Binder: QOpenGLVertexArrayObject::Binder class is a convenience class to help with the binding and releasing of OpenGL Vertex Array Objects
- QOpenGLBuffer: Functions for creating and managing OpenGL buffer objects
- QOpenGLDebugLogger: Enables logging of OpenGL debugging messages
- QOpenGLDebugMessage: Wraps an OpenGL debug message
- QOpenGLFramebufferObject: Encapsulates an OpenGL framebuffer object
- QOpenGLFramebufferObjectFormat: Specifies the format of an OpenGL framebuffer object
- QOpenGLFunctions_2_0: All functions for OpenGL 2.0 specification
- QOpenGLFunctions_2_1: All functions for OpenGL 2.1 specification
- QOpenGLFunctions_4_1_Core: All functions for OpenGL 4.1 core profile
- QOpenGLPaintDevice: Enables painting to an OpenGL context using QPainter
- QOpenGLPixelTransferOptions: Describes the pixel storage modes that affect the unpacking of pixels during texture upload
- QOpenGLShader: Allows OpenGL shaders to be compiled
- QOpenGLShaderProgram: Allows OpenGL shader programs to be linked and used
- QOpenGLTexture: Encapsulates an OpenGL texture object
- QOpenGLTextureBlitter: Convenient way to draw textured quads via OpenGL
- QOpenGLTimeMonitor: Wraps a sequence of OpenGL timer query objects
- QOpenGLTimerQuery: Wraps an OpenGL timer query object
- QOpenGLVersionFunctionsFactory: Provides access to OpenGL functions for a specified version and profile
- QOpenGLVersionProfile: Represents the version and if applicable the profile of an OpenGL context
- QOpenGLVertexArrayObject: Wraps an OpenGL Vertex Array Object
- QOpenGLWindow: Convenience subclass of QWindow to perform OpenGL painting

### QtOpenGLWidgets (1)

- QOpenGLWidget: Widget for rendering OpenGL graphics

### QtCharts (49)

- QAbstractAxis: Base class used for specialized axis classes
- QAbstractBarSeries: Abstract parent class for all bar series classes
- QAbstractSeries: Base class for all Qt Chart series
- QAreaLegendMarker: Legend marker for an area series
- QAreaSeries: Presents data in area charts
- QBarCategoryAxis: Adds categories to a chart's axes
- QBarLegendMarker: Legend marker for a bar series
- QBarSeries: Presents a series of data as vertical bars grouped by category
- QBarSet: Represents one set of bars in a bar chart
- QBoxPlotLegendMarker: Legend marker for a box plot series
- QBoxPlotSeries: Presents data in box-and-whiskers charts
- QBoxSet: Represents one item in a box-and-whiskers chart
- QCandlestickLegendMarker: Legend marker for a candlestick series
- QCandlestickModelMapper: Abstract model mapper class for candlestick series
- QCandlestickSeries: Presents data as candlesticks
- QCandlestickSet: Represents a single candlestick item in a candlestick chart
- QCategoryAxis: Places named ranges on the axis
- QChart: Manages the graphical representation of the chart's series, legends, and axes
- QChartView: Standalone widget that can display charts
- QColorAxis: Displays a color scale as one of the chart's axes
- QDateTimeAxis: Adds dates and times to a chart's axis
- QHBarModelMapper: Horizontal model mapper for bar series
- QHBoxPlotModelMapper: Horizontal model mapper for box plot series
- QHCandlestickModelMapper: Horizontal model mapper for a candlestick series
- QHorizontalBarSeries: Presents a series of data as horizontal bars grouped by category
- QHorizontalPercentBarSeries: Presents a series of categorized data as a percentage of each category
- QHorizontalStackedBarSeries: Presents a series of data as horizontally stacked bars, with one bar per category
- QHPieModelMapper: Horizontal model mapper for pie series
- QHXYModelMapper: Horizontal model mapper for line, spline, and scatter series
- QLegend: Displays the legend of a chart
- QLegendMarker: Abstract object that can be used to access markers within a legend
- QLineSeries: Presents data in line charts
- QLogValueAxis: Adds a logarithmic scale to a chart's axis
- QPercentBarSeries: Presents a series of categorized data as a percentage of each category
- QPieLegendMarker: Legend marker for a pie series
- QPieSeries: Presents data in pie charts
- QPieSlice: Represents a single slice in a pie series
- QPolarChart: Presents data in polar charts
- QScatterSeries: Presents data in scatter charts
- QSplineSeries: Presents data as spline charts
- QStackedBarSeries: Presents a series of data as vertically stacked bars, with one bar per category
- QValueAxis: Adds values to a chart's axes
- QVBarModelMapper: Vertical model mapper for bar series
- QVBoxPlotModelMapper: Vertical model mapper for box plot series
- QVCandlestickModelMapper: Vertical model mapper for a candlestick series
- QVPieModelMapper: Vertical model mapper for pie series
- QVXYModelMapper: Vertical model mapper for line, spline, and scatter series
- QXYLegendMarker: Legend marker for a line, spline, or scatter series
- QXYSeries: Base class for line, spline, and scatter series

### QtDesigner (26)

- QAbstractExtensionFactory: Interface for extension factories in Qt Widgets Designer
- QAbstractExtensionManager: Interface for extension managers in Qt Widgets Designer
- QAbstractFormBuilder: Default implementation for classes that create user interfaces at run-time
- QDesignerActionEditorInterface: Allows you to change the focus of Qt Widgets Designer's action editor
- QDesignerContainerExtension: Allows you to add pages to a custom multi-page container in Qt Widgets Designer's workspace
- QDesignerCustomWidgetCollectionInterface: Allows you to include several custom widgets in one single library
- QDesignerCustomWidgetInterface: Enables Qt Widgets Designer to access and construct custom widgets
- QDesignerFormEditorInterface: Allows you to access Qt Widgets Designer's various components
- QDesignerFormWindowCursorInterface: Allows you to query and modify a form window's widget selection, and in addition modify the properties of all the form's widgets
- QDesignerFormWindowInterface: Allows you to query and manipulate form windows appearing in Qt Widgets Designer's workspace
- QDesignerFormWindowManagerInterface: Allows you to manipulate the collection of form windows in Qt Widgets Designer, and control Qt Widgets Designer's form editing actions
- QDesignerMemberSheetExtension: Allows you to manipulate a widget's member functions which is displayed when configuring connections using Qt Widgets Designer's mode for editing signals and slots
- QDesignerObjectInspectorInterface: Allows you to change the focus of Qt Widgets Designer's object inspector
- QDesignerPropertyEditorInterface: Allows you to query and manipulate the current state of Qt Widgets Designer's property editor
- QDesignerPropertySheetExtension: Allows you to manipulate a widget's properties which is displayed in Qt Designer's property editor
- QDesignerTaskMenuExtension: Allows you to add custom menu entries to Qt Widgets Designer's task menu
- QDesignerWidgetBoxInterface: Allows you to control the contents of Qt Widgets Designer's widget box
- QExtensionFactory: Allows you to create a factory that is able to make instances of custom extensions in Qt Designer
- QExtensionManager: Extension management facilities for Qt Widgets Designer
- QFormBuilder: Used to dynamically construct user interfaces from UI files at run-time
- QPyDesignerContainerExtension
- QPyDesignerCustomWidgetCollectionPlugin
- QPyDesignerCustomWidgetPlugin
- QPyDesignerMemberSheetExtension
- QPyDesignerPropertySheetExtension
- QPyDesignerTaskMenuExtension

### QtHelp (18)

- QCompressedHelpInfo: Access to the details about a compressed help file
- QHelpContentItem: Item for use with QHelpContentModel
- QHelpContentModel: Model that supplies content to views
- QHelpContentWidget: Tree view for displaying help content model items
- QHelpEngine: Access to contents and indices of the help engine
- QHelpEngineCore: The core functionality of the help system
- QHelpFilterData: Details for the filters used by QHelpFilterEngine
- QHelpFilterEngine: Filtered view of the help contents
- QHelpFilterSettingsWidget: Widget that allows for creating, editing and removing filters
- QHelpIndexModel: Model that supplies index keywords to views
- QHelpIndexWidget: List view displaying the QHelpIndexModel
- QHelpLink
- QHelpSearchEngine: Access to widgets reusable to integrate fulltext search as well as to index and search documentation
- QHelpSearchEngineCore: Access to index and search documentation
- QHelpSearchQuery: Contains the field name and the associated search term
- QHelpSearchQueryWidget: Simple line edit or an advanced widget to enable the user to input a search term in a standardized input mask
- QHelpSearchResult: The data associated with the search result
- QHelpSearchResultWidget: Text browser to display search results

### QtNetworkAuth (10)

- QAbstractOAuth: The base of all implementations of OAuth authentication methods
- QAbstractOAuth2: The base of all implementations of OAuth 2 authentication methods
- QAbstractOAuthReplyHandler: Handles replies to OAuth authentication requests
- QOAuth1: Implementation of the OAuth 1 Protocol
- QOAuth1Signature: Implements OAuth 1 signature methods
- QOAuth2AuthorizationCodeFlow: Implementation of the Authorization Code Grant flow
- QOAuth2DeviceAuthorizationFlow: Implementation of the Device Authorization Grant flow
- QOAuthHttpServerReplyHandler
- QOAuthOobReplyHandler
- QOAuthUriSchemeReplyHandler: Handles private/custom and https URI scheme redirects

### QtWebSockets (6)

- QMaskGenerator: Abstract base for custom 32-bit mask generators
- QWebSocket: Implements a TCP socket that talks the WebSocket protocol
- QWebSocketCorsAuthenticator: Authenticator object for Cross Origin Requests (CORS)
- QWebSocketHandshakeOptions: Collects options for the WebSocket handshake
- QWebSocketProtocol
- QWebSocketServer: Implements a WebSocket-based server

### QtSerialPort (2)

- QSerialPort: Provides functions to access serial ports
- QSerialPortInfo: Provides information about existing serial ports

### QtStateMachine (12)

- QAbstractState
- QAbstractTransition
- QEventTransition
- QFinalState
- QHistoryState
- QKeyEventTransition
- QMouseEventTransition
- QStateMachine.SignalEvent
- QSignalTransition
- QState
- QStateMachine
- QStateMachine.WrappedEvent

### QtQml (28)

- QJSEngine: Environment for evaluating JavaScript code
- QJSManagedValue: Represents a value on the JavaScript heap belonging to a QJSEngine
- QJSPrimitiveNull
- QJSPrimitiveUndefined
- QJSPrimitiveValue: Operates on primitive types in JavaScript semantics
- QJSValue: Acts as a container for Qt/JavaScript data types
- QJSValueIterator: Java-style iterator for QJSValue
- QQmlContext.PropertyPair
- QQmlAbstractUrlInterceptor: Allows you to control QML file loading
- QQmlApplicationEngine: Convenient way to load an application from a single QML file
- QQmlComponent: Encapsulates a QML component definition
- QQmlContext: Defines a context within a QML engine
- QQmlEngine: Environment for instantiating QML components
- QQmlEngineExtensionPlugin: Abstract base for custom QML extension plugins
- QQmlError: Encapsulates a QML error
- QQmlExpression: Evaluates JavaScript in a QML context
- QQmlExtensionPlugin: Abstract base for custom QML extension plugins with custom type registration functions
- QQmlFileSelector: A class for applying a QFileSelector to QML file loading
- QQmlImageProviderBase: Used to register image providers in the QML engine
- QQmlIncubationController: Instances drive the progress of QQmlIncubators
- QQmlIncubator: Allows QML objects to be created asynchronously
- QQmlListReference: Allows the manipulation of QQmlListProperty properties
- QQmlNetworkAccessManagerFactory: Creates QNetworkAccessManager instances for a QML engine
- QQmlParserStatus: Updates on the QML parser state
- QQmlProperty: Abstracts accessing properties on objects created from QML
- QQmlPropertyMap: Allows you to set key-value pairs that can be used in QML bindings
- QQmlPropertyValueSource: Interface for property value sources such as animations and bindings
- QQmlScriptString: Encapsulates a script and its context

### QtQuick (51)

- QSGGeometry.Attribute
- QSGGeometry.AttributeSet
- QSGGeometry.ColoredPoint2D
- QSGMaterialShader.GraphicsPipelineState
- QQuickItem.ItemChangeData
- QSGGeometry.Point2D
- QQuickAsyncImageProvider: Interface for asynchronous control of QML image requests
- QQuickFramebufferObject: Convenience class for integrating OpenGL rendering using a framebuffer object (FBO) with Qt Quick
- QQuickGraphicsConfiguration: Controls lower level graphics settings for the QQuickWindow
- QQuickGraphicsDevice: Opaque container for native graphics objects representing graphics devices or contexts
- QQuickImageProvider: Interface for supporting pixmaps and threaded image requests in QML
- QQuickImageResponse: Interface for asynchronous image loading in QQuickAsyncImageProvider
- QQuickItem: The most basic of all visual items in Qt Quick
- QQuickItemGrabResult: Contains the result from QQuickItem::grabToImage()
- QQuickPaintedItem: Way to use the QPainter API in the QML Scene Graph
- QQuickRenderControl: Mechanism for rendering the Qt Quick scenegraph onto an offscreen render target in a fully application-controlled manner
- QQuickRenderTarget: Opaque container for native graphics resources specifying a render target, and associated metadata
- QQuickTextDocument: Access to the QTextDocument of QQuickTextEdit
- QQuickTextureFactory: Interface for loading custom textures from QML
- QQuickView: Window for displaying a Qt Quick user interface
- QQuickWindow: The window for displaying a graphical QML scene
- QQuickFramebufferObject.Renderer
- QSGMaterialShader.RenderState: Encapsulates the current rendering state during a call to QSGMaterialShader::updateUniformData() and the other update type of functions
- QSGRenderNode.RenderState
- QSGBasicGeometryNode: Serves as a baseclass for geometry based nodes
- QSGClipNode: Implements the clipping functionality in the scene graph
- QSGDynamicTexture: Serves as a baseclass for dynamically changing textures, such as content that is rendered to FBO's
- QSGFlatColorMaterial: Convenient way of rendering solid colored geometry in the scene graph
- QSGGeometry: Low-level storage for graphics primitives in the Qt Quick Scene Graph
- QSGGeometryNode: Used for all rendered content in the scene graph
- QSGImageNode: Provided for convenience to easily draw textured content using the QML scene graph
- QSGMaterial: Encapsulates rendering state for a shader program
- QSGMaterialShader: Represents a graphics API independent shader program
- QSGMaterialType
- QSGNode: The base class for all nodes in the scene graph
- QSGOpacityNode: Used to change opacity of nodes
- QSGOpaqueTextureMaterial: Convenient way of rendering textured geometry in the scene graph
- QNativeInterface.QSGOpenGLTexture
- QSGRectangleNode: Convenience class for drawing solid filled rectangles using scenegraph
- QSGRendererInterface: An interface providing access to some of the graphics API specific internals of the scenegraph
- QSGRenderNode: Represents a set of custom rendering commands targeting the graphics API that is in use by the scenegraph
- QSGSimpleRectNode: Convenience class for drawing solid filled rectangles using scenegraph
- QSGSimpleTextureNode: Provided for convenience to easily draw textured content using the QML scene graph
- QSGTextNode: Class for drawing text layouts and text documents in the Qt Quick scene graph
- QSGTexture: The base class for textures used in the scene graph
- QSGTextureMaterial: Convenient way of rendering textured geometry in the scene graph
- QSGTextureProvider: Encapsulates texture based entities in QML
- QSGTransformNode: Implements transformations in the scene graph
- QSGVertexColorMaterial: Convenient way of rendering per-vertex colored geometry in the scene graph
- QSGGeometry.TexturedPoint2D
- QQuickItem.UpdatePaintNodeData

### QtQuickWidgets (1)

- QQuickWidget: Widget for displaying a Qt Quick user interface

### QtQuick3D (6)

- QQuick3DGeometry.Attribute
- QQuick3D: Helper class for selecting correct surface format
- QQuick3DGeometry: Base class for defining custom geometry
- QQuick3DObject: Base class of all 3D nodes and resources
- QQuick3DTextureData: Base class for defining custom texture data
- QQuick3DGeometry.TargetAttribute

### QtWebEngineQuick (2)

- QQuickWebEngineProfile: Web engine profile shared by multiple pages
- QtWebEngineQuick

### QtRemoteObjects (11)

- QAbstractItemModelReplica: Serves as a convenience class for Replicas of Sources based on QAbstractItemModel
- QRemoteObjectAbstractPersistedStore: A class which provides the methods for setting PROP values of a replica to value they had the last time the replica was used
- QRemoteObjectDynamicReplica: A dynamically instantiated Replica
- QRemoteObjectHost: A (Host) Node on a Qt Remote Objects network
- QRemoteObjectHostBase: Base functionality common to Host and RegistryHost classes
- QRemoteObjectNode: A node on a Qt Remote Objects network
- QRemoteObjectRegistry: A class holding information about Source objects available on the Qt Remote Objects network
- QRemoteObjectRegistryHost: A (Host/Registry) node on a Qt Remote Objects network
- QRemoteObjectReplica: A class interacting with (but not implementing) a Qt API on the Remote Object network
- QtRemoteObjects
- QRemoteObjectSourceLocationInfo

### QtPositioning (16)

- QGeoAddress: Represents an address of a QGeoLocation
- QGeoAreaMonitorInfo: Describes the parameters of an area or region to be monitored for proximity
- QGeoAreaMonitorSource: Enables the detection of proximity changes for a specified set of coordinates
- QGeoCircle: Defines a circular geographic area
- QGeoCoordinate: Defines a geographical position on the surface of the Earth
- QGeoLocation: Represents basic information about a location
- QGeoPath: Defines a geographic path
- QGeoPolygon: Defines a geographic polygon
- QGeoPositionInfo: Contains information gathered on a global position, direction and velocity at a particular point in time
- QGeoPositionInfoSource: Abstract base class for the distribution of positional updates
- QGeoRectangle: Defines a rectangular geographic area
- QGeoSatelliteInfo: Contains basic information about a satellite
- QGeoSatelliteInfoSource: Abstract base class for the distribution of satellite information updates
- QGeoShape: Defines a geographic area
- QNmeaPositionInfoSource: Positional information using a NMEA data source
- QNmeaSatelliteInfoSource: Satellite information using an NMEA data source

### QtSensors (52)

- QAccelerometer: Convenience wrapper around QSensor
- QAccelerometerFilter: Convenience wrapper around QSensorFilter
- QAccelerometerReading: Reports on linear acceleration along the X, Y and Z axes
- QAmbientLightFilter: Convenience wrapper around QSensorFilter
- QAmbientLightReading: Represents one reading from the ambient light sensor
- QAmbientLightSensor: Convenience wrapper around QSensor
- QAmbientTemperatureFilter: Convenience wrapper around QSensorFilter
- QAmbientTemperatureReading: Holds readings of the ambient temperature
- QAmbientTemperatureSensor: Convenience wrapper around QSensor
- QCompass: Convenience wrapper around QSensor
- QCompassFilter: Convenience wrapper around QSensorFilter
- QCompassReading: Represents one reading from a compass
- QGyroscope: Convenience wrapper around QSensor
- QGyroscopeFilter: Convenience wrapper around QSensorFilter
- QGyroscopeReading: Represents one reading from the gyroscope sensor
- QHumidityFilter: Convenience wrapper around QSensorFilter
- QHumidityReading: Holds readings from the humidity sensor
- QHumiditySensor: Convenience wrapper around QSensor
- QIRProximityFilter
- QIRProximityReading
- QIRProximitySensor
- QLidFilter
- QLidReading
- QLidSensor
- QLightFilter: Convenience wrapper around QSensorFilter
- QLightReading: Represents one reading from the light sensor
- QLightSensor: Convenience wrapper around QSensor
- QMagnetometer: Convenience wrapper around QSensor
- QMagnetometerFilter: Convenience wrapper around QSensorFilter
- QMagnetometerReading: Represents one reading from the magnetometer
- QOrientationFilter: Convenience wrapper around QSensorFilter
- QOrientationReading: Represents one reading from the orientation sensor
- QOrientationSensor: Convenience wrapper around QSensor
- QPressureFilter: Convenience wrapper around QSensorFilter
- QPressureReading: Holds readings from the pressure sensor
- QPressureSensor: Convenience wrapper around QSensor
- QProximityFilter: Convenience wrapper around QSensorFilter
- QProximityReading: Represents one reading from the proximity sensor
- QProximitySensor: Convenience wrapper around QSensor
- qoutputrange
- QRotationFilter: Convenience wrapper around QSensorFilter
- QRotationReading: Represents one reading from the rotation sensor
- QRotationSensor: Convenience wrapper around QSensor
- QSensor: Represents a single hardware sensor
- QSensorFilter: Efficient callback facility for asynchronous notifications of sensor changes
- QSensorReading: Holds the readings from the sensor
- QTapFilter
- QTapReading
- QTapSensor
- QTiltFilter: Convenience wrapper around QSensorFilter
- QTiltReading: Holds readings from the tilt sensor
- QTiltSensor: Convenience wrapper around QSensor

### QtBluetooth (22)

- QLowEnergyAdvertisingParameters.AddressInfo: QLowEnergyAdvertisingParameters::AddressInfo defines the elements of a white list
- QBluetooth
- QBluetoothAddress: Assigns an address to the Bluetooth device
- QBluetoothDeviceDiscoveryAgent: Discovers the Bluetooth devices nearby
- QBluetoothDeviceInfo: Stores information about the Bluetooth device
- QBluetoothHostInfo: Encapsulates the details of a local QBluetooth device
- QBluetoothLocalDevice: Enables access to the local Bluetooth device
- QBluetoothServer: Uses the RFCOMM or L2cap protocol to communicate with a Bluetooth device
- QBluetoothServiceDiscoveryAgent: Enables you to query for Bluetooth services
- QBluetoothServiceInfo: Enables access to the attributes of a Bluetooth service
- QBluetoothSocket: Enables connection to a Bluetooth device running a bluetooth server
- QBluetoothUuid: Generates a UUID for each Bluetooth service
- QLowEnergyAdvertisingData: Represents the data to be broadcast during Bluetooth Low Energy advertising
- QLowEnergyAdvertisingParameters: Represents the parameters used for Bluetooth Low Energy advertising
- QLowEnergyCharacteristic: Stores information about a Bluetooth Low Energy service characteristic
- QLowEnergyCharacteristicData: Used to set up GATT service data
- QLowEnergyConnectionParameters: Used when requesting or reporting an update of the parameters of a Bluetooth LE connection
- QLowEnergyController: Access to Bluetooth Low Energy Devices
- QLowEnergyDescriptor: Stores information about the Bluetooth Low Energy descriptor
- QLowEnergyDescriptorData: Used to create GATT service data
- QLowEnergyService: Represents an individual service on a Bluetooth Low Energy Device
- QLowEnergyServiceData: Used to set up GATT service data

### QtNfc (11)

- QNdefFilter: Filter for matching NDEF messages
- QNdefMessage: NFC NDEF message
- QNdefNfcIconRecord: NFC MIME record to hold an icon
- QNdefNfcSmartPosterRecord: NFC RTD-SmartPoster
- QNdefNfcTextRecord: NFC RTD-Text
- QNdefNfcUriRecord: NFC RTD-URI
- QNdefRecord: NFC NDEF record
- QNearFieldManager: Access to notifications for NFC events
- QNearFieldTarget: Interface for communicating with a target device
- QNdefFilter.Record
- QNearFieldTarget.RequestId: A request id handle

### QtSpatialAudio (5)

- QAmbientSound: A stereo overlay sound
- QAudioEngine: Manages a three dimensional sound field
- QAudioListener: Defines the position and orientation of the person listening to a sound field defined by QAudioEngine
- QAudioRoom
- QSpatialSound: A sound object in 3D space

### QAxContainer (6)

- QAxBase: Abstract class that provides an API to initialize and access a COM object
- QAxBaseObject: Static properties and signals for QAxObject
- QAxBaseWidget: Static properties and signals for QAxWidget
- QAxObject: QObject that wraps a COM object
- QAxObjectInterface: Interface providing common properties of QAxObject and QAxWidget
- QAxWidget: QWidget that wraps an ActiveX control

### QtGraphs (47)

- Q3DScene: Description of the 3D scene being visualized
- QAbstract3DAxis: Base class for the axes of a 3D graph
- QAbstract3DSeries: Base class for all 3D data series
- QAbstractAxis: Base class used for specialized axis classes
- QAbstractDataProxy: Base class for all 3D graph proxies
- QAbstractSeries: Base class for all Qt Graphs for 2D series
- QAreaSeries: Presents data in area graphs
- QBar3DSeries: Represents a data series in a 3D bar graph
- QBarCategoryAxis: Adds categories to a graph's axes
- QBarDataItem: Container for resolved data to be added to bar graphs
- QBarDataProxy: The data proxy for a 3D bars graph
- QBarModelMapper: Model mapper for bar series
- QBarSeries: Presents data in bar graphs
- QBarSet: Represents one set of bars in a bar graph
- QCategory3DAxis: Manipulates an axis of a graph
- QCustom3DItem: Adds a custom item to a graph
- QCustom3DLabel: Adds a custom label to a graph
- QCustom3DVolume: Adds a volume rendered object to a graph
- QCustomSeries: Allows presenting customized graph types
- QDateTimeAxis: Adds support for DateTime values to be added to a graph's axis
- QtGraphs3D
- QGraphsLine
- QGraphsTheme: Visual style for graphs
- QHeightMapSurfaceDataProxy: Base proxy class for Q3DSurfaceWidgetItem
- QItemModelBarDataProxy: Proxy class for presenting data in item models with Q3DBarsWidgetItem
- QItemModelScatterDataProxy: Proxy class for presenting data in item models with Q3DScatterWidgetItem
- QItemModelSurfaceDataProxy: Proxy class for presenting data in item models with Q3DSurfaceWidgetItem
- QLegendData
- QLineSeries: Presents data in line graphs
- QLogValue3DAxisFormatter: Formatting rules for a logarithmic value axis
- QPieModelMapper: Model mapper for pie series
- QPieSeries: Presents data in pie graphs
- QPieSlice: Represents a single slice in a pie series
- QScatter3DSeries: Represents a data series in a 3D scatter graph
- QScatterDataItem: Container for resolved data to be added to scatter graphs
- QScatterDataProxy: The data proxy for 3D scatter graphs
- QScatterSeries: Presents data in scatter graphs
- QSpline3DSeries: Represents a data series as a spline
- QSplineSeries: Presents data in spline graphs
- QSurface3DSeries: Represents a data series in a 3D surface graph
- QSurfaceDataItem: Container for resolved data to be added to surface graphs
- QSurfaceDataProxy: The data proxy for a 3D surface graph
- QValue3DAxis: Manipulates an axis of a graph
- QValue3DAxisFormatter: Base class for 3D value axis formatters
- QValueAxis: Adds values to a graph's axes
- QXYModelMapper: Model mapper for line, spline, and scatter series
- QXYSeries: Parent class for all x & y series classes

### QtGraphsWidgets (4)

- Q3DBarsWidgetItem
- Q3DGraphsWidgetItem
- Q3DScatterWidgetItem
- Q3DSurfaceWidgetItem

### QtDataVisualization (35)

- Q3DBars: Methods for rendering 3D bar graphs
- Q3DCamera: Representation of a camera in 3D space
- Q3DInputHandler: Basic wheel mouse based input handler
- Q3DLight: Representation of a light source in 3D space
- Q3DObject: Simple base class for all the objects in a 3D scene
- Q3DScatter: Methods for rendering 3D scatter graphs
- Q3DScene: Description of the 3D scene being visualized
- Q3DSurface: Methods for rendering 3D surface plots
- Q3DTheme: Visual style for graphs
- QAbstract3DAxis: Base class for the axes of a graph
- QAbstract3DGraph: Window and render loop for graphs
- QAbstract3DInputHandler: Base class for implementations of input handlers
- QAbstract3DSeries: Base class for all data series
- QAbstractDataProxy: Base class for all data visualization data proxies
- QBar3DSeries: Represents a data series in a 3D bar graph
- QBarDataItem: Container for resolved data to be added to bar graphs
- QBarDataProxy: The data proxy for a 3D bars graph
- QCategory3DAxis: Manipulates an axis of a graph
- QCustom3DItem: Adds a custom item to a graph
- QCustom3DLabel: Adds a custom label to a graph
- QCustom3DVolume: Adds a volume rendered object to a graph
- QHeightMapSurfaceDataProxy: Base proxy class for Q3DSurface
- QItemModelBarDataProxy: Proxy class for presenting data in item models with Q3DBars
- QItemModelScatterDataProxy: Proxy class for presenting data in item models with Q3DScatter
- QItemModelSurfaceDataProxy: Proxy class for presenting data in item models with Q3DSurface
- QLogValue3DAxisFormatter: Formatting rules for a logarithmic value axis
- QScatter3DSeries: Represents a data series in a 3D scatter graph
- QScatterDataItem: Container for resolved data to be added to scatter graphs
- QScatterDataProxy: The data proxy for 3D scatter graphs
- QSurface3DSeries: Represents a data series in a 3D surface graph
- QSurfaceDataItem: Container for resolved data to be added to surface graphs
- QSurfaceDataProxy: The data proxy for a 3D surface graph
- QTouch3DInputHandler: Basic touch display based input handler
- QValue3DAxis: Manipulates an axis of a graph
- QValue3DAxisFormatter: Base class for value axis formatters

### Qt3DCore (22)

- QAbstractAspect: The base class for aspects that provide a vertical slice of behavior
- QAbstractFunctor: Abstract base class for all functors
- QAbstractSkeleton: A skeleton contains the joints for a skinned mesh
- QArmature: Used to calculate skinning transform matrices and set them on shaders
- QAspectEngine: Responsible for handling all the QAbstractAspect subclasses that have been registered with the scene
- QAttribute: Defines an attribute and how data should be read from a QBuffer
- QBackendNode: Base class for all Qt3D backend nodes
- QBackendNodeMapper: Creates and maps backend nodes to their respective frontend nodes
- QBoundingVolume: Can be used to override the bounding volume of an entity
- QBuffer: Provides a data store for raw data to later be used as vertices or uniforms
- QComponent: Base class of scene nodes that can be aggregated by Qt3DCore::QEntity instances as a component
- QCoreSettings: Holds settings related to core data handling process
- QEntity: Qt3DCore::QEntity is a Qt3DCore::QNode subclass that can aggregate several Qt3DCore::QComponent instances that will specify its behavior
- QGeometry: Encapsulates geometry
- QGeometryView: Encapsulates geometry details
- QJoint: Used to transforms parts of skinned meshes
- QNode: The base class of all Qt3D node classes used to build a Qt3D scene
- QNodeId: Uniquely identifies a QNode
- QNodeIdTypePair
- QSkeleton: Holds the data for a skeleton to be used with skinned meshes
- QSkeletonLoader: Used to load a skeleton of joints from file
- QTransform: Used to perform transforms on meshes

### Qt3DRender (114)

- QAbstractLight: Encapsulate a QAbstractLight object in a Qt 3D scene
- QAbstractRayCaster: An abstract base class for ray casting in 3d scenes
- QAbstractTexture: A base class to be used to provide textures
- QAbstractTextureImage: Encapsulates the necessary information to create an OpenGL texture image
- QAlphaCoverage: Enable alpha-to-coverage multisampling mode
- QAlphaTest: Specify alpha reference test
- QBlendEquation: Specifies the equation used for both the RGB blend equation and the Alpha blend equation
- QBlendEquationArguments: Encapsulates blending information: specifies how the incoming values (what's going to be drawn) are going to affect the existing values (what is already drawn)
- QBlitFramebuffer: FrameGraph node to transfer a rectangle of pixel values from one region of a render target to another
- QCamera: Defines a view point through which the scene will be rendered
- QCameraLens: Qt3DRender::QCameraLens specifies the projection matrix that will be used to define a Camera for a 3D scene
- QCameraSelector: Class to allow for selection of camera to be used
- QClearBuffers: Class to clear buffers
- QClipPlane: Enables an additional OpenGL clipping plane that can be in shaders using gl_ClipDistance
- QColorMask: Allows specifying which color components should be written to the currently bound frame buffer
- QComputeCommand: QComponent to issue work for the compute shader on GPU
- QCullFace: Specifies whether front or back face culling is enabled
- QDepthRange: Enables remapping depth values written into the depth buffer
- QDepthTest: Tests the fragment shader's depth value against the depth of a sample being written to
- QDirectionalLight: Encapsulate a Directional Light object in a Qt 3D scene
- QDispatchCompute: FrameGraph node to issue work for the compute shader on GPU
- QDithering: Enable dithering
- QEffect: Base class for effects in a Qt 3D scene
- QEnvironmentLight: Encapsulate an environment light object in a Qt 3D scene
- QFilterKey: Storage for filter keys and their values
- QFrameGraphNode: Base class of all FrameGraph configuration nodes
- QFrontFace: Defines front and back facing polygons
- QFrustumCulling: Enable frustum culling for the FrameGraph
- QGeometryRenderer: Encapsulates geometry rendering
- QGraphicsApiFilter: Identifies the API required for the attached QTechnique
- QLayer: Way of filtering which entities will be rendered
- QLayerFilter: Controls layers drawn in a frame graph branch
- QLevelOfDetail: Way of controlling the complexity of rendered entities based on their size on the screen
- QLevelOfDetailBoundingSphere: Simple spherical volume, defined by its center and radius
- QLevelOfDetailSwitch: Provides a way of enabling child entities based on distance or screen size
- QLineWidth: Specifies the width of rasterized lines
- QMaterial: Provides an abstract class that should be the base of all material component classes in a scene
- QMemoryBarrier: Class to emplace a memory barrier
- QMesh: A custom mesh loader
- QMultiSampleAntiAliasing: Enable multisample antialiasing
- QNoDepthMask: Disable depth write
- QNoDraw: When a Qt3DRender::QNoDraw node is present in a FrameGraph branch, this prevents the renderer from rendering any primitive
- QNoPicking: When a Qt3DRender::QNoPicking node is present in a FrameGraph branch, this prevents the render aspect from performing picking selection for the given branch
- QObjectPicker: Instantiates a component that can be used to interact with a QEntity by a process known as picking
- QPaintedTextureImage: A QAbstractTextureImage that can be written through a QPainter
- QParameter: Provides storage for a name and value pair. This maps to a shader uniform
- QPickEvent: Holds information when an object is picked
- QPickingProxy: Can be used to provide an alternate QGeometryView used only for picking
- QPickingSettings: Specifies how entity picking is handled
- QPickLineEvent: Holds information when a segment of a line is picked
- QPickPointEvent: Holds information when a segment of a point cloud is picked
- QPickTriangleEvent: Holds information when a triangle is picked
- QPointLight: Encapsulate a Point Light object in a Qt 3D scene
- QPointSize: Specifies the size of rasterized points. May either be set statically or by shader programs
- QPolygonOffset: Sets the scale and steps to calculate depth values for polygon offsets
- PropertyReaderInterface
- QProximityFilter: Select entities which are within a distance threshold of a target entity
- QRasterMode: Render state allows to control the type of rasterization to be performed
- QRayCaster: Qt3DRender::QRayCaster is used to perform ray casting tests in 3d world coordinates
- QRayCasterHit: Details of a hit when casting a ray through a model
- Render
- QRenderAspect: Class
- QRenderCapabilities: Holds settings related to available rendering engines
- QRenderCapture: Frame graph node for render capture
- QRenderCaptureReply: Receives the result of render capture request
- QRenderPass: Encapsulates a Render Pass
- QRenderPassFilter: Provides storage for vectors of Filter Keys and Parameters
- QRenderSettings: Holds settings related to rendering process and host the active FrameGraph
- QRenderState: An abstract base class for all render states
- QRenderStateSet: FrameGraph node offers a way of specifying a set of QRenderState objects to be applied during the execution of a framegraph branch
- QRenderSurfaceSelector: Provides a way of specifying the render surface
- QRenderTarget: Encapsulates a target (usually a frame buffer object) which the renderer can render into
- QRenderTargetOutput: Allows the specification of an attachment of a render target (whether it is a color texture, a depth texture, etc... )
- QRenderTargetSelector: Provides a way of specifying a render target
- QSceneLoader: Provides the facility to load an existing Scene
- QScissorTest: Discards fragments that fall outside of a certain rectangular portion of the screen
- QScreenRayCaster: Performe ray casting test based on screen coordinates
- QSeamlessCubemap: Enables seamless cubemap texture filtering
- QSetFence: FrameGraphNode used to insert a fence in the graphics command stream
- QShaderData: Provides a way of specifying values of a Uniform Block or a shader structure
- QShaderImage: Provides Image access to shader programs
- QShaderProgram: Encapsulates a Shader Program
- QShaderProgramBuilder: Generates a Shader Program content from loaded graphs
- QSharedGLTexture: Allows to use a textureId from a separate OpenGL context in a Qt 3D scene
- QSortPolicy: Provides storage for the sort types to be used
- QSpotLight: Encapsulate a Spot Light object in a Qt 3D scene
- QStencilMask: Controls the front and back writing of individual bits in the stencil planes
- QStencilOperation: Specifies stencil operation
- QStencilOperationArguments: Sets the actions to be taken when stencil and depth tests fail
- QStencilTest: Specifies arguments for the stecil test
- QStencilTestArguments: Specifies arguments for stencil test
- QSubtreeEnabler: Enables or disables entire subtrees of framegraph nodes
- QTechnique: Encapsulates a Technique
- QTechniqueFilter: A QFrameGraphNode used to select QTechniques to use
- QTexture1D: A QAbstractTexture with a Target1D target format
- QTexture1DArray: A QAbstractTexture with a Target1DArray target format
- QTexture2D: A QAbstractTexture with a Target2D target format
- QTexture2DArray: A QAbstractTexture with a Target2DArray target format
- QTexture2DMultisample: A QAbstractTexture with a Target2DMultisample target format
- QTexture2DMultisampleArray: A QAbstractTexture with a Target2DMultisampleArray target format
- QTexture3D: A QAbstractTexture with a Target3D target format
- QTextureBuffer: A QAbstractTexture with a TargetBuffer target format
- QTextureCubeMap: A QAbstractTexture with a TargetCubeMap target format
- QTextureCubeMapArray: A QAbstractTexture with a TargetCubeMapArray target format
- QTextureData: Stores texture information such as the target, height, width, depth, layers, wrap, and if mipmaps are enabled
- QTextureDataUpdate: Holds content and information required to perform partial updates of a texture content
- QTextureImage: Encapsulates the necessary information to create an OpenGL texture image from an image source
- QTextureImageData: Stores data representing a texture
- QTextureImageDataGenerator: Provides texture image data for QAbstractTextureImage
- QTextureLoader: Handles the texture loading and setting the texture's properties
- QTextureRectangle: A QAbstractTexture with a TargetRectangle target format
- QTextureWrapMode: Defines the wrap mode a Qt3DRender::QAbstractTexture should apply to a texture
- QViewport: A viewport on the Qt3D Scene
- QWaitFence: FrameGraphNode used to wait for a fence in the graphics command stream to become signaled

### Qt3DInput (22)

- QAbstractActionInput: The base class for the Action Input and all Aggregate Action Inputs
- QAbstractAxisInput: QAbstractActionInput is the base class for all Axis Input
- QAbstractPhysicalDevice: The base class used by Qt3d to interact with arbitrary input devices
- QAction: Links a set of QAbstractActionInput that trigger the same event
- QActionInput: Stores Device and Buttons used to trigger an input event
- QAnalogAxisInput: An axis input controlled by an analog input The axis value is controlled like a traditional analog input such as a joystick
- QAxis: Stores QAbstractAxisInputs used to trigger an input event
- QAxisAccumulator: Processes velocity or acceleration data from a QAxis
- QAxisSetting: Stores settings for the specified list of Axis
- QButtonAxisInput: An axis input controlled by buttons The axis value is controlled by buttons rather than a traditional analog input such as a joystick
- QInputAspect: Responsible for creating physical devices and handling associated jobs
- QInputChord: Represents a set of QAbstractActionInput's that must be triggerd at once
- QInputSequence: Represents a set of QAbstractActionInput's that must be triggerd one after the other
- QInputSettings: Holds the pointer to an input event source object
- QKeyboardDevice: In charge of dispatching keyboard events to attached QQKeyboardHandler objects
- QKeyboardHandler: Provides keyboard event notification
- QKeyEvent: Event type send by KeyBoardHandler
- QLogicalDevice: Allows the user to define a set of actions that they wish to use within an application
- QMouseDevice: Delegates mouse events to the attached MouseHandler objects
- QMouseEvent: Qt3DCore::QMouseEvent contains parameters that describe a mouse event
- QMouseHandler: Provides a means of being notified about mouse events when attached to a QMouseDevice instance
- QWheelEvent: Contains parameters that describe a mouse wheel event

### Qt3DLogic (2)

- QFrameAction: Provides a way to have a synchronous function executed each frame
- QLogicAspect: Responsible for handling frame synchronization jobs

### Qt3DExtras (44)

- Qt3DWindow
- QAbstractCameraController: Basic functionality for camera controllers
- QAbstractSpriteSheet
- QConeGeometry: Allows creation of a cone in 3D space
- QConeGeometryView: A conical mesh
- QConeMesh: A conical mesh
- QCuboidGeometry: Allows creation of a cuboid in 3D space
- QCuboidGeometryView: A cuboid mesh
- QCuboidMesh: A cuboid mesh
- QCylinderGeometry: Allows creation of a cylinder in 3D space
- QCylinderGeometryView: A cylindrical mesh
- QCylinderMesh: A cylindrical mesh
- QDiffuseMapMaterial: Default implementation of the phong lighting effect where the diffuse light component is read from a texture map
- QDiffuseSpecularMapMaterial: Default implementation of the phong lighting effect where the diffuse and specular light components are read from texture maps
- QDiffuseSpecularMaterial: Default implementation of the phong lighting effect
- QExtrudedTextGeometry: Allows creation of a 3D extruded text in 3D space
- QExtrudedTextMesh: A 3D extruded Text mesh
- QFirstPersonCameraController: Allows controlling the scene camera from the first person perspective
- QForwardRenderer: Default FrameGraph implementation of a forward renderer
- QGoochMaterial: Material that implements the Gooch shading model, popular in CAD and CAM applications
- QMetalRoughMaterial: Default implementation of PBR lighting
- QMorphPhongMaterial: Default implementation of the phong lighting effect
- QNormalDiffuseMapAlphaMaterial: Specialization of QNormalDiffuseMapMaterial with alpha coverage and a depth test performed in the rendering pass
- QNormalDiffuseMapMaterial: Default implementation of the phong lighting and bump effect where the diffuse light component is read from a texture map and the normals of the mesh being rendered from a normal texture map
- QNormalDiffuseSpecularMapMaterial: Default implementation of the phong lighting and bump effect where the diffuse and specular light components are read from texture maps and the normals of the mesh being rendered from a normal texture map
- QOrbitCameraController: Allows controlling the scene camera along orbital path
- QPerVertexColorMaterial: Default implementation for rendering the color properties set for each vertex
- QPhongAlphaMaterial: Default implementation of the phong lighting effect with alpha
- QPhongMaterial: Default implementation of the phong lighting effect
- QPlaneGeometry: Allows creation of a plane in 3D space
- QPlaneGeometryView: A square planar mesh
- QPlaneMesh: A square planar mesh
- QSkyboxEntity: Qt3DExtras::QSkyboxEntity is a convenience Qt3DCore::QEntity subclass that can be used to insert a skybox in a 3D scene
- QSphereGeometry: Allows creation of a sphere in 3D space
- QSphereGeometryView: A spherical mesh
- QSphereMesh: A spherical mesh
- QSpriteGrid
- QSpriteSheet
- QSpriteSheetItem
- QText2DEntity: Allows creation of a 2D text in 3D space
- QTextureMaterial: Default implementation of a simple unlit texture material
- QTorusGeometry: Allows creation of a torus in 3D space
- QTorusGeometryView: A toroidal mesh
- QTorusMesh: A toroidal mesh

### Qt3DAnimation (27)

- QAbstractAnimation: An abstract base class for Qt3D animations
- QAbstractAnimationClip: The base class for types providing key frame animation data
- QAbstractChannelMapping
- QAbstractClipAnimator: The base class for types providing animation playback capabilities
- QAbstractClipBlendNode: The base class for types used to construct animation blend trees
- QAdditiveClipBlend: Performs an additive blend of two animation clips based on an additive factor
- QAnimationAspect: Provides key-frame animation capabilities to Qt 3D
- QAnimationClip: Specifies key frame animation data
- QAnimationClipData: Class containing the animation data
- QAnimationClipLoader: Enables loading key frame animation data from a file
- QAnimationController: A controller class for animations
- QAnimationGroup: A class grouping animations together
- QBlendedClipAnimator: Component providing animation playback capabilities of a tree of blend nodes
- QChannel: Defines a channel for a QAnimationClipData. The animation system interpolates each channel component independently except in the case the QChannel is called "Rotation" (case sensitive), it has four QChannelComponents and the same number of keyframes for each QChannelComponent. In that case the interpolation will be performed using SLERP
- QChannelComponent
- QChannelMapper: Allows to map the channels within the clip onto properties of objects in the application
- QChannelMapping: Allows to map the channels within the clip onto properties of objects in the application
- QClipAnimator: Component providing simple animation playback capabilities
- QClipBlendValue: Class used for including a clip in a blend tree
- QClock
- QKeyFrame: A base class for handling keyframes
- QKeyframeAnimation: A class implementing simple keyframe animation to a QTransform
- QLerpClipBlend: Performs a linear interpolation of two animation clips based on a normalized factor
- QMorphingAnimation: A class implementing blend-shape morphing animation
- QMorphTarget: A class providing morph targets to blend-shape animation
- QSkeletonMapping
- QVertexBlendAnimation: A class implementing vertex-blend morphing animation
