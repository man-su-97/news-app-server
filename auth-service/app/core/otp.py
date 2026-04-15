import random

def generate_otp(length: int = 6) -> str:
  """
  Generates a random OTP (One-Time Password) of the given length.
  Args:
    length (int, optional): The length of the OTP to generate. Defaults to 6.
  Returns:
    str: A random OTP of the given length.
  """
  return "".join(
      str(random.randint(0, 9))
      for _ in range(length)
  )