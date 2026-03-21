import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / ".github" / "scripts" / "clear-execstack.py"
SPEC = importlib.util.spec_from_file_location("whatsapp_clear_execstack", SCRIPT)
assert SPEC and SPEC.loader
clear_execstack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clear_execstack)


class ClearExecstackTests(unittest.TestCase):
    def test_clear_execstack_removes_execute_bit_from_gnu_stack(self):
        source = Path("/bin/true")
        self.assertTrue(source.exists(), "/bin/true is required for this test")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "true"
            shutil.copy2(source, target)

            with target.open("r+b") as handle:
                headers = clear_execstack._gnu_stack_flag_offsets(handle)
                self.assertTrue(headers, "Expected PT_GNU_STACK in copied ELF")
                for flag_offset, flags, endian in headers:
                    handle.seek(flag_offset)
                    handle.write(
                        clear_execstack.struct.pack(
                            endian + "I",
                            flags | clear_execstack.PF_X,
                        )
                    )

            self.assertTrue(clear_execstack.has_executable_stack(target))
            self.assertTrue(clear_execstack.clear_execstack(target))
            self.assertFalse(clear_execstack.has_executable_stack(target))


if __name__ == "__main__":
    unittest.main()
