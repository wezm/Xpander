from . import conf, manager, service, XInterface, gtkui, app

"""Main application class"""
class App:
    def __init__(self):
        self._hotkeys_manager = manager.Hotkeys()
        self._conf_manager = manager.Conf(self._hotkeys_manager)

        self._phrases_manager = manager.Phrases(self._hotkeys_manager)
        self._service = service.Service()
        self._interface = XInterface.Interface(self.handle_key_event)

    def start(self):
        self._hotkeys_manager.grab_hotkeys()
        # Necessary to actually grab tab key, hopefully focus is not
        # in a textbox during startup.
        self._interface.send_string('\t')

        self._service.start()
        self._interface.start()
        gtkui.Indicator(
            config_manager=self._conf_manager,
            phrases_manager=self._phrases_manager,
            quit_callback=self.stop,
            toggle_service_callback=self.toggle_service,
            restart_callback=self.stop
        )

    def stop(self):
        self._interface.stop()
        self._service.stop()

    def toggle_service(self):
        self._service.toggle_service()
        return conf._run_service # FIXME: Don't reach into conf

    def handle_key_event(self, *args):
        self._service(*args)
