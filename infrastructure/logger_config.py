import logging
from pythonjsonlogger import jsonlogger
import os
from datetime import datetime
import json

# Diretório do log (opcional)
LOG_FILE = "hedge.log"
TRADE_LOG_FILE = "hedge_trades.log"
# -------------------------------
# Formatter bonito para o console
# -------------------------------
class PrettyJsonFormatter(jsonlogger.JsonFormatter):
    def __init__(self, *args, **kwargs):
        kwargs["json_serializer"] = json.dumps  # força uso explícito do json
        super().__init__(*args, **kwargs)

    def format(self, record):
        log_record = record.__dict__.copy()

        # Converter datetime para ISO string
        for key, value in log_record.items():
            if hasattr(value, "isoformat"):
                log_record[key] = value.isoformat()

        log_record["timestamp"] = datetime.utcnow().isoformat()

        # Usar indentação amigável
        return self.json_serializer(log_record, indent=2)

# -------------------------------
# Formatter compacto para o arquivo
# -------------------------------
class CompactJsonFormatter(jsonlogger.JsonFormatter):
    def process_log_record(self, log_record):
        log_record["timestamp"] = datetime.utcnow().isoformat()
        for k, v in log_record.items():
            if hasattr(v, "isoformat"):
                log_record[k] = v.isoformat()
        return super().process_log_record(log_record)

# -------------------------------
# Logger configurado
# -------------------------------
logger = logging.getLogger("hedge_logger")
logger.setLevel(logging.INFO)
logger.propagate = False  # evita logs duplicados

# Console Handler (compacto)
console_handler = logging.StreamHandler()
console_handler.setFormatter(CompactJsonFormatter())

# Arquivo Handler (compacto)
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(CompactJsonFormatter())

# Adiciona ambos
if not logger.hasHandlers():
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

# Logger para operações Binance
trade_logger = logging.getLogger("hedge_trade_logger")
trade_logger.setLevel(logging.INFO)
trade_logger.propagate = False

trade_log_file = "hedge_trades.log"
trade_file_handler = logging.FileHandler(TRADE_LOG_FILE)
trade_file_handler.setFormatter(CompactJsonFormatter())

if not trade_logger.hasHandlers():
    trade_logger.addHandler(trade_file_handler)