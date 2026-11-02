class ReviewFailure(ValueError):
    """Safe, structured failure without provider text or submitted material."""
    def __init__(self, code, metadata=None, transient=False):
        super().__init__(code)
        self.code = code
        self.metadata = metadata if metadata is not None else {}
        self.transient = transient
